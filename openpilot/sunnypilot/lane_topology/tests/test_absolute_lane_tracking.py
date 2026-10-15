from openpilot.sunnypilot.lane_topology.absolute_lane import AbsoluteLaneGate, explicit_carriageway_edges
from openpilot.sunnypilot.lane_topology.tracker import LaneTopologyTracker
from openpilot.sunnypilot.lane_topology.types import LaneBoundaryObservation, LaneMarkingType

ROAD_EDGE = LaneMarkingType.roadEdge
DIVIDER = LaneMarkingType.dashed


def carriageway(lateral: list[float], markings: list[LaneMarkingType] | None = None) -> tuple[LaneBoundaryObservation, ...]:
  types = markings if markings is not None else [ROAD_EDGE] + [DIVIDER] * (len(lateral) - 2) + [ROAD_EDGE]
  return tuple(
    LaneBoundaryObservation(source_id=index, points=((0.0, y), (30.0, y)), marking_type=marking, confidence=0.9)
    for index, (y, marking) in enumerate(zip(lateral, types, strict=True))
  )


def drive(gate: AbsoluteLaneGate, tracker: LaneTopologyTracker, frames, *, session_id: str = 'session',
          route_revision: int = 1, start_ns: int = 1_000_000_000, ego_y_m: float = 0.0):
  """Feed frames through the shared tracker and the gate, as a live consumer would."""
  decisions = []
  for step, observations in enumerate(frames):
    timestamp_ns = start_ns + step * 100_000_000
    topology = tracker.update(observations, frame_id=step, timestamp_ns=timestamp_ns)
    edges = explicit_carriageway_edges(topology.boundaries)
    if edges is None:
      decisions.append(None)
      continue
    decisions.append(gate.update(topology.boundaries, left_edge_track_id=edges[0], right_edge_track_id=edges[1],
                                 frame_id=step, timestamp_ns=timestamp_ns, session_id=session_id,
                                 route_revision=route_revision, topology_state=topology.state, ego_y_m=ego_y_m))
  return decisions


def test_the_shared_tracker_and_gate_agree_and_need_three_consistent_frames():
  tracker = LaneTopologyTracker()
  gate = AbsoluteLaneGate()
  lateral = [5.25, 1.75, -1.75, -5.25]
  frames = [carriageway(lateral)] * 3

  decisions = drive(gate, tracker, frames)

  assert [decision.valid for decision in decisions] == [False, False, True]
  confirmed = decisions[-1]
  assert (confirmed.lane_index, confirmed.lane_count) == (2, 3)
  # The tracker's own visible index must agree with the absolute index here.
  topology = tracker.update(carriageway(lateral), frame_id=9, timestamp_ns=9_000_000_000)
  assert topology.ego_lane_index_from_left + 1 == 2


def test_a_lane_change_needs_its_own_three_frames():
  tracker = LaneTopologyTracker()
  gate = AbsoluteLaneGate()
  lateral = [5.25, 1.75, -1.75, -5.25]
  decisions = drive(gate, tracker, [carriageway(lateral)] * 3, ego_y_m=0.0)
  assert decisions[-1].lane_index == 2

  decisions = drive(gate, tracker, [carriageway(lateral)] * 3, ego_y_m=3.5, start_ns=1_300_000_000)
  assert [decision.valid for decision in decisions] == [False, False, True]
  assert decisions[-1].lane_index == 1 and decisions[-1].lane_count == 3


def test_a_new_lane_appearing_on_the_left_requires_reconfirmation():
  tracker = LaneTopologyTracker()
  gate = AbsoluteLaneGate()
  decisions = drive(gate, tracker, [carriageway([5.25, 1.75, -1.75, -5.25])] * 3)
  assert (decisions[-1].lane_index, decisions[-1].lane_count) == (2, 3)

  # A fourth lane opens on the left, so the carriageway edge itself moves.
  wider = carriageway([8.75, 5.25, 1.75, -1.75, -5.25])
  decisions = drive(gate, tracker, [wider] * 3, start_ns=1_300_000_000)
  assert [decision.valid for decision in decisions] == [False, False, True]
  assert (decisions[-1].lane_index, decisions[-1].lane_count) == (3, 4)


def test_a_missing_interior_line_never_becomes_an_absolute_index():
  tracker = LaneTopologyTracker()
  gate = AbsoluteLaneGate()
  without_divider = carriageway([5.25, -1.75, -5.25])

  decisions = drive(gate, tracker, [without_divider] * 4)

  assert all(decision is not None for decision in decisions)
  assert all(not decision.valid for decision in decisions)
  # One over-wide space means the divider was never observed. The tracker drops
  # invisible boundaries before the shared geometry, so the ego cannot be placed
  # and the gate sees an ambiguous topology rather than an inner gap.
  assert {decision.reason for decision in decisions} <= {
    'topology:ambiguous', 'implausibleLaneWidth', 'interiorBoundaryNotVisible'}


def test_losing_a_divider_after_a_confirmation_clears_the_index():
  lateral = [5.25, 1.75, -1.75, -5.25]
  tracker = LaneTopologyTracker()
  gate = AbsoluteLaneGate()
  assert drive(gate, tracker, [carriageway(lateral)] * 3)[-1].valid

  lost = drive(gate, tracker, [carriageway([5.25, -1.75, -5.25])] * 3, start_ns=1_300_000_000)

  assert all(decision is not None and not decision.valid for decision in lost)


def test_a_session_or_route_change_clears_the_confirmed_index():
  lateral = [5.25, 1.75, -1.75, -5.25]
  tracker = LaneTopologyTracker()
  gate = AbsoluteLaneGate()
  assert drive(gate, tracker, [carriageway(lateral)] * 3)[-1].valid

  other_session = drive(gate, tracker, [carriageway(lateral)] * 3, session_id='other',
                        start_ns=1_300_000_000)
  assert [decision.valid for decision in other_session] == [False, False, True]

  tracker.reset()
  other_route = drive(gate, tracker, [carriageway(lateral)] * 3, route_revision=9,
                      start_ns=1_600_000_000)
  assert [decision.valid for decision in other_route] == [False, False, True]


def test_a_low_confidence_divider_blocks_the_absolute_index():
  tracker = LaneTopologyTracker()
  gate = AbsoluteLaneGate()
  weak = tuple(
    LaneBoundaryObservation(source_id=index, points=((0.0, y), (30.0, y)), marking_type=marking,
                            confidence=0.05 if index in (1, 2) else 0.9)
    for index, (y, marking) in enumerate(zip([5.25, 1.75, -1.75, -5.25],
                                             [ROAD_EDGE, DIVIDER, DIVIDER, ROAD_EDGE], strict=True))
  )

  decisions = drive(gate, tracker, [weak] * 4)

  assert all(decision is not None and not decision.valid for decision in decisions)
