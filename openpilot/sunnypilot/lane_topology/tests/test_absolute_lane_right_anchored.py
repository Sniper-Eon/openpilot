"""The right-edge-anchored gate: one carriageway edge plus a map total.

The shipped gate needs both carriageway edges. On real wide-camera frames the
left one is never found, while the right one (the shoulder line) is what the
observer actually traces. These tests pin the reduced-evidence design and, just
as importantly, pin what it still refuses.
"""
from dataclasses import replace
from types import SimpleNamespace

from openpilot.sunnypilot.lane_topology.absolute_lane import (
  AbsoluteLaneGate,
  RightEdgeAnchoredGate,
)
from openpilot.sunnypilot.lane_topology.types import LaneBoundary, LaneMarkingType, LaneTopologyState
from openpilot.sunnypilot.navassist.position_feedback import lane_position_feedback
from openpilot.sunnypilot.navassist.road_lane_position import publish_decision

LANE_M = 3.5
START_NS = 1_000_000_000
STEP_NS = 100_000_000
# A four lane carriageway: median at +7, three dividers, shoulder edge at -7.
LANES_LEFT_TO_RIGHT = (5.25, 1.75, -1.75, -5.25)
RIGHT_EDGE_Y = -7.0


def boundary(track_id: int, y: float, marking_type: LaneMarkingType = LaneMarkingType.dashed,
             confidence: float = 1.0, visible: bool = True) -> LaneBoundary:
  return LaneBoundary(track_id, ((0.0, y), (30.0, y)), marking_type, confidence, visible=visible)


def full_carriageway() -> tuple[LaneBoundary, ...]:
  return (
    boundary(1, 7.0, LaneMarkingType.doubleSolid),
    boundary(2, 3.5),
    boundary(3, 0.0),
    boundary(4, -3.5),
    boundary(5, RIGHT_EDGE_Y, LaneMarkingType.roadEdge),
  )


def settle(gate: RightEdgeAnchoredGate, boundaries, *, ego_y_m: float, lane_total: int | None = 4,
           frames: int = 3, start_ns: int = START_NS, session_id: str = 'session',
           route_revision: int = 1, state: LaneTopologyState = LaneTopologyState.normal,
           right_edge: int = 5, confidence: float | None = None):
  if confidence is not None:
    boundaries = tuple(replace(b, confidence=confidence) if b.track_id == right_edge else b
                        for b in boundaries)
  decision = None
  for step in range(frames):
    decision = gate.update(boundaries, right_edge_track_id=right_edge, lane_total=lane_total,
                           frame_id=step, timestamp_ns=start_ns + step * STEP_NS,
                           session_id=session_id, route_revision=route_revision,
                           topology_state=state, ego_y_m=ego_y_m)
  return decision


def test_each_lane_is_numbered_from_the_shoulder_edge():
  for expected, ego_y in enumerate(LANES_LEFT_TO_RIGHT, start=1):
    decision = settle(RightEdgeAnchoredGate(), full_carriageway(), ego_y_m=ego_y)

    assert decision.valid is True, (expected, ego_y, decision.reason)
    assert decision.lane_index == expected and decision.lane_count == 4


def test_the_total_comes_from_the_map_and_is_reported_verbatim():
  decision = settle(RightEdgeAnchoredGate(), full_carriageway(), ego_y_m=1.75, lane_total=4)

  assert decision.valid is True
  assert decision.lane_count == 4 and decision.lane_index == 2


def test_lines_left_of_the_ego_do_not_change_the_answer():
  # The design's point: the median and the dividers to the left are irrelevant,
  # so their absence is not a reason to refuse.
  only_right_side = (
    boundary(3, 0.0),
    boundary(4, -3.5),
    boundary(5, RIGHT_EDGE_Y, LaneMarkingType.roadEdge),
  )

  decision = settle(RightEdgeAnchoredGate(), only_right_side, ego_y_m=1.75)

  assert decision.valid is True and decision.lane_index == 2
  # The shipped both-edge gate cannot answer on exactly this input.
  both_edges = AbsoluteLaneGate()
  shipped = both_edges.update(only_right_side, left_edge_track_id=3, right_edge_track_id=5,
                              frame_id=0, timestamp_ns=START_NS, session_id='session', route_revision=1,
                              topology_state=LaneTopologyState.normal, ego_y_m=1.75)
  assert shipped.valid is False


def test_a_missing_line_between_the_ego_and_the_shoulder_is_refused():
  # Divider 4 is gone, so the space the ego sits in would look two lanes wide.
  missing_divider = (
    boundary(1, 7.0, LaneMarkingType.doubleSolid),
    boundary(2, 3.5),
    boundary(3, 0.0),
    boundary(5, RIGHT_EDGE_Y, LaneMarkingType.roadEdge),
  )

  decision = settle(RightEdgeAnchoredGate(), missing_divider, ego_y_m=-1.75)

  assert decision.valid is False and decision.reason == 'implausibleLaneWidth'


def test_a_double_counted_line_is_refused():
  spurious = full_carriageway() + (boundary(6, -5.25),)

  decision = settle(RightEdgeAnchoredGate(), spurious, ego_y_m=-1.75, right_edge=5)

  assert decision.valid is False and decision.reason == 'implausibleLaneWidth'


def test_without_a_map_total_nothing_is_claimed():
  for total in (None, 0, -1, 13, True, 4.0):
    decision = settle(RightEdgeAnchoredGate(), full_carriageway(), ego_y_m=1.75, lane_total=total)
    assert decision.valid is False and decision.reason == 'laneTotalUnavailable', total


def test_a_total_that_contradicts_the_anchor_is_refused():
  # Three lines lie between the ego and the shoulder, so a three lane road cannot
  # also contain the ego.
  decision = settle(RightEdgeAnchoredGate(), full_carriageway(), ego_y_m=5.25, lane_total=3)

  assert decision.valid is False and decision.reason == 'mapTotalInconsistent'


def test_the_edge_itself_must_be_typed_visible_and_confident():
  untyped = tuple(replace(b, marking_type=LaneMarkingType.dashed) if b.track_id == 5 else b
                  for b in full_carriageway())
  invisible = tuple(replace(b, visible=False) if b.track_id == 5 else b for b in full_carriageway())
  weak = tuple(replace(b, confidence=0.1) if b.track_id == 5 else b for b in full_carriageway())

  assert settle(RightEdgeAnchoredGate(), untyped, ego_y_m=1.75).reason == 'edgeMarkingNotConfirmed'
  assert settle(RightEdgeAnchoredGate(), invisible, ego_y_m=1.75).reason == 'edgeNotVisible'
  assert settle(RightEdgeAnchoredGate(), weak, ego_y_m=1.75).reason == 'lowConfidenceBoundary'


def test_the_edge_must_be_observed_and_be_the_outermost_boundary():
  without_edge = tuple(b for b in full_carriageway() if b.track_id != 5)
  beyond_edge = full_carriageway() + (boundary(9, -10.5),)

  assert settle(RightEdgeAnchoredGate(), without_edge, ego_y_m=1.75).reason == 'carriagewayEdgeNotObserved'
  assert settle(RightEdgeAnchoredGate(), beyond_edge, ego_y_m=1.75).reason == 'boundaryOutsideCarriageway'


def test_an_interior_line_that_is_not_visible_or_confident_is_refused():
  carried = tuple(replace(b, visible=False) if b.track_id == 4 else b for b in full_carriageway())
  weak = tuple(replace(b, confidence=0.1) if b.track_id == 4 else b for b in full_carriageway())

  assert settle(RightEdgeAnchoredGate(), carried, ego_y_m=-1.75).reason == 'interiorBoundaryNotVisible'
  assert settle(RightEdgeAnchoredGate(), weak, ego_y_m=-1.75).reason == 'lowConfidenceBoundary'


def test_an_ego_right_of_the_shoulder_edge_has_no_lane():
  decision = settle(RightEdgeAnchoredGate(), full_carriageway(), ego_y_m=-7.5)

  assert decision.valid is False and decision.reason == 'implausibleLaneWidth'


def test_merges_splits_and_ambiguity_always_refuse():
  for state in (LaneTopologyState.mergingLeft, LaneTopologyState.splittingRight,
                LaneTopologyState.ambiguous, LaneTopologyState.stale):
    decision = settle(RightEdgeAnchoredGate(), full_carriageway(), ego_y_m=1.75, state=state)
    assert decision.valid is False and decision.reason == f'topology:{state.name}'


def test_three_consistent_frames_sessions_routes_and_gaps_are_required():
  gate = RightEdgeAnchoredGate()
  assert settle(gate, full_carriageway(), ego_y_m=1.75, frames=1).valid is False
  assert settle(gate, full_carriageway(), ego_y_m=1.75, frames=2).valid is False
  confirmed = settle(gate, full_carriageway(), ego_y_m=1.75, frames=3)
  assert confirmed.valid is True and confirmed.stable_samples == 3

  # A new navigation session must re-earn the window.
  fresh = settle(gate, full_carriageway(), ego_y_m=1.75, session_id='other', frames=2)
  assert fresh.valid is False and fresh.stable_samples == 2

  # A long gap in the frame stream also resets it.
  gate2 = RightEdgeAnchoredGate()
  settle(gate2, full_carriageway(), ego_y_m=1.75, frames=1)
  late = settle(gate2, full_carriageway(), ego_y_m=1.75, frames=1, start_ns=START_NS + 900_000_000)
  assert late.valid is False and late.stable_samples == 1


def test_a_confirmed_right_anchored_decision_plugs_into_the_verified_producer(tmp_path):
  path = tmp_path / 'road_lane_position.json'
  decision = settle(RightEdgeAnchoredGate(), full_carriageway(), ego_y_m=1.75)
  assert decision.valid is True

  record = publish_decision(decision, nav_session_id='nav', route_revision=7, path=path,
                            now_ns=START_NS + 2 * STEP_NS)

  assert record['valid'] is True and record['lane_index'] == 2 and record['lane_count'] == 4
  value = lane_position_feedback(SimpleNamespace(session_id='nav', route_revision=7), path=path,
                                 now_ns=START_NS + 2 * STEP_NS)
  assert value['valid'] is True and value['laneIndex'] == 2 and value['laneCount'] == 4
