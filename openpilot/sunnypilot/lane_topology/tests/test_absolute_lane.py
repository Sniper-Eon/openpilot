from openpilot.sunnypilot.lane_topology.absolute_lane import (
  AbsoluteLaneGate,
  explicit_carriageway_edges,
)
from openpilot.sunnypilot.lane_topology.types import LaneBoundary, LaneMarkingType, LaneTopologyState


def boundary(track_id: int, y: float, marking_type: LaneMarkingType = LaneMarkingType.unknown,
             confidence: float = 1.0, visible: bool = True) -> LaneBoundary:
  return LaneBoundary(track_id, ((0.0, y), (30.0, y)), marking_type, confidence, visible=visible)


def three_lane_carriageway() -> tuple[LaneBoundary, ...]:
  """Left road edge, two dividers and a right road edge: three 3.5 m lanes."""
  return (
    boundary(10, 5.25, LaneMarkingType.roadEdge),
    boundary(11, 1.75, LaneMarkingType.dashed),
    boundary(12, -1.75, LaneMarkingType.dashed),
    boundary(13, -5.25, LaneMarkingType.roadEdge),
  )


def settled(gate: AbsoluteLaneGate, boundaries, *, ego_y_m: float = 0.0, session_id: str = 'session',
            route_revision: int = 1, start_ns: int = 1_000_000_000, state: LaneTopologyState = LaneTopologyState.normal,
            left_edge: int = 10, right_edge: int = 13, samples: int = 3):
  decision = None
  for step in range(samples):
    decision = gate.update(boundaries, left_edge_track_id=left_edge, right_edge_track_id=right_edge,
                           frame_id=step, timestamp_ns=start_ns + step * 100_000_000, session_id=session_id,
                           route_revision=route_revision, topology_state=state, ego_y_m=ego_y_m)
  return decision


def test_visible_corridor_without_typed_edges_is_never_numbered():
  # The recorded 2026-10-15 road test produced exactly this: one visible space
  # bounded by untyped boundaries.
  gate = AbsoluteLaneGate()
  decision = settled(gate, (boundary(1, 1.8), boundary(2, -1.8)), samples=5, left_edge=1, right_edge=2)

  assert decision.valid is False and decision.lane_index is None
  assert decision.reason == 'edgeMarkingNotConfirmed'


def test_a_typed_three_lane_carriageway_confirms_only_after_three_stable_frames():
  gate = AbsoluteLaneGate()
  first = gate.update(three_lane_carriageway(), left_edge_track_id=10, right_edge_track_id=13,
                      frame_id=0, timestamp_ns=1_000_000_000, session_id='s', route_revision=1)
  second = gate.update(three_lane_carriageway(), left_edge_track_id=10, right_edge_track_id=13,
                       frame_id=1, timestamp_ns=1_100_000_000, session_id='s', route_revision=1)
  third = gate.update(three_lane_carriageway(), left_edge_track_id=10, right_edge_track_id=13,
                      frame_id=2, timestamp_ns=1_200_000_000, session_id='s', route_revision=1)

  assert (first.valid, first.reason) == (False, 'stabilizing')
  assert (second.valid, second.reason) == (False, 'stabilizing') and second.stable_samples == 2
  assert third.valid and third.lane_index == 2 and third.lane_count == 3 and third.stable_samples == 3
  assert third.capture_mono_ns == 1_200_000_000


def test_leftmost_and_rightmost_lanes_number_from_the_left():
  assert settled(AbsoluteLaneGate(), three_lane_carriageway(), ego_y_m=3.5).lane_index == 1
  assert settled(AbsoluteLaneGate(), three_lane_carriageway(), ego_y_m=-3.5).lane_index == 3


def test_a_missing_interior_line_makes_the_space_implausible():
  # Without the first divider the remaining space would be two lanes wide.
  boundaries = (
    boundary(10, 5.25, LaneMarkingType.roadEdge),
    boundary(12, -1.75, LaneMarkingType.dashed),
    boundary(13, -5.25, LaneMarkingType.roadEdge),
  )
  decision = settled(AbsoluteLaneGate(), boundaries)

  assert not decision.valid and decision.reason == 'implausibleLaneWidth'


def test_a_boundary_outside_the_claimed_edges_leaves_a_lane_unaccounted():
  boundaries = (boundary(9, 8.75, LaneMarkingType.roadEdge),) + three_lane_carriageway()
  decision = settled(AbsoluteLaneGate(), boundaries)

  assert not decision.valid and decision.reason == 'boundaryOutsideCarriageway'


def test_a_carried_over_interior_line_or_a_weak_line_stays_unknown():
  carried = (
    boundary(10, 5.25, LaneMarkingType.roadEdge),
    boundary(11, 1.75, LaneMarkingType.dashed, visible=False),
    boundary(13, -5.25, LaneMarkingType.roadEdge),
  )
  weak = (
    boundary(10, 5.25, LaneMarkingType.roadEdge),
    boundary(11, 1.75, LaneMarkingType.dashed, confidence=0.10),
    boundary(13, -5.25, LaneMarkingType.roadEdge),
  )

  assert settled(AbsoluteLaneGate(), carried).reason == 'interiorBoundaryNotVisible'
  assert settled(AbsoluteLaneGate(), weak).reason == 'lowConfidenceBoundary'


def test_a_double_line_centerline_is_a_left_edge_but_not_a_right_edge():
  two_lane = (
    boundary(10, 5.25, LaneMarkingType.doubleSolid),
    boundary(11, 1.75, LaneMarkingType.dashed),
    boundary(13, -1.75, LaneMarkingType.roadEdge),
  )
  shifted = two_lane[:2] + (boundary(13, -1.75, LaneMarkingType.doubleSolid),)

  assert settled(AbsoluteLaneGate(), two_lane).lane_index == 2
  assert settled(AbsoluteLaneGate(), shifted).reason == 'edgeMarkingNotConfirmed'


def test_merge_split_and_ambiguous_topology_always_refuse():
  for state in (LaneTopologyState.mergingLeft, LaneTopologyState.mergingRight,
                LaneTopologyState.splittingLeft, LaneTopologyState.splittingRight,
                LaneTopologyState.ambiguous, LaneTopologyState.stale):
    decision = settled(AbsoluteLaneGate(), three_lane_carriageway(), state=state)
    assert not decision.valid, state
    assert decision.reason == f'topology:{state.name}'


def test_session_route_and_timing_breaks_restart_the_stability_window():
  boundaries = three_lane_carriageway()
  gate = AbsoluteLaneGate()
  assert settled(gate, boundaries, session_id='a').valid
  # A new navigation session must not inherit the previous confirmation.
  assert not settled(gate, boundaries, session_id='b', samples=1).valid
  assert settled(gate, boundaries, session_id='b', samples=3).valid

  gate.reset()
  assert settled(gate, boundaries, route_revision=7).valid
  assert not settled(gate, boundaries, route_revision=8, samples=2).valid

  gate.reset()
  gate.update(boundaries, left_edge_track_id=10, right_edge_track_id=13, frame_id=0,
              timestamp_ns=1_000_000_000, session_id='s', route_revision=1)
  late = gate.update(boundaries, left_edge_track_id=10, right_edge_track_id=13, frame_id=1,
                     timestamp_ns=1_000_000_000 + 900_000_000, session_id='s', route_revision=1)
  assert not late.valid and late.stable_samples == 1
  repeated = gate.update(boundaries, left_edge_track_id=10, right_edge_track_id=13, frame_id=2,
                         timestamp_ns=1_000_000_000 + 900_000_000, session_id='s', route_revision=1)
  assert not repeated.valid and repeated.stable_samples == 1


def test_an_alternating_answer_never_accumulates_evidence():
  gate = AbsoluteLaneGate()
  for step, ego in enumerate((0.0, 3.5, 0.0, 3.5, 0.0, 3.5)):
    decision = gate.update(three_lane_carriageway(), left_edge_track_id=10, right_edge_track_id=13,
                           frame_id=step, timestamp_ns=1_000_000_000 + step * 100_000_000,
                           session_id='s', route_revision=1, ego_y_m=ego)
    assert not decision.valid and decision.stable_samples == 1


def test_more_than_twelve_lanes_is_refused():
  boundaries = tuple(boundary(100 + index, 22.75 - 3.5 * index, LaneMarkingType.roadEdge
                              if index in (0, 13) else LaneMarkingType.dashed) for index in range(14))
  decision = settled(AbsoluteLaneGate(), boundaries, left_edge=100, right_edge=113)

  assert not decision.valid and decision.reason == 'laneRangeExceeded'


def test_edge_helper_only_accepts_outermost_typed_edges():
  assert explicit_carriageway_edges((boundary(1, 1.8), boundary(2, -1.8))) is None
  assert explicit_carriageway_edges(three_lane_carriageway()) == (10, 13)
  extra = (boundary(9, 8.75, LaneMarkingType.roadEdge),) + three_lane_carriageway()
  # The helper reports the outermost typed pair; the gate is what refuses the
  # extra boundary, so both layers are exercised.
  assert explicit_carriageway_edges(extra) == (9, 13)
  assert explicit_carriageway_edges((boundary(1, 1.8, LaneMarkingType.roadEdge),)) is None
