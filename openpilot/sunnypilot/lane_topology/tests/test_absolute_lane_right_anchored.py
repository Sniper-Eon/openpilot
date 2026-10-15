"""The lane-anchored gate: outermost lane marking plus a map total.

The shipped gate needs both carriageway edges. On real wide-camera frames the
left one is never found, while the right one is what observers do trace. The
anchor here is the outermost **lane marking**, never the road edge: measured on a
real segment the road edge sits a median of 2.1 m beyond the ego lane's right
line, which is a shoulder, and counting it as a lane shifts the answer by one.
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

START_NS = 1_000_000_000
STEP_NS = 100_000_000
# Four lanes: five lane lines, the outermost at -7.0, and a 2.1 m shoulder beyond.
LANE_CENTRES = (5.25, 1.75, -1.75, -5.25)
ANCHOR = 5
SHOULDER_Y = -9.1


def boundary(track_id: int, y: float, marking_type: LaneMarkingType = LaneMarkingType.dashed,
             confidence: float = 1.0, visible: bool = True) -> LaneBoundary:
  return LaneBoundary(track_id, ((0.0, y), (30.0, y)), marking_type, confidence, visible=visible)


def carriageway() -> tuple[LaneBoundary, ...]:
  return (
    boundary(1, 7.0, LaneMarkingType.doubleSolid),
    boundary(2, 3.5),
    boundary(3, 0.0),
    boundary(4, -3.5),
    boundary(ANCHOR, -7.0, LaneMarkingType.solid),
    boundary(6, SHOULDER_Y, LaneMarkingType.roadEdge),
  )


def settle(gate: RightEdgeAnchoredGate, boundaries, *, ego_y_m: float, lane_total: int | None = 4,
           frames: int = 3, start_ns: int = START_NS, session_id: str = 'session',
           route_revision: int = 1, state: LaneTopologyState = LaneTopologyState.normal,
           anchor: int = ANCHOR):
  decision = None
  for step in range(frames):
    decision = gate.update(boundaries, right_anchor_track_id=anchor, lane_total=lane_total,
                           frame_id=step, timestamp_ns=start_ns + step * STEP_NS,
                           session_id=session_id, route_revision=route_revision,
                           topology_state=state, ego_y_m=ego_y_m)
  return decision


def test_each_lane_is_numbered_from_the_outermost_lane_marking():
  for expected, ego_y in enumerate(LANE_CENTRES, start=1):
    decision = settle(RightEdgeAnchoredGate(), carriageway(), ego_y_m=ego_y)

    assert decision.valid is True, (expected, ego_y, decision.reason)
    assert decision.lane_index == expected and decision.lane_count == 4


def test_the_road_edge_is_never_the_anchor():
  # Handing the shoulder edge in as the anchor is the off-by-one trap.
  decision = settle(RightEdgeAnchoredGate(), carriageway(), ego_y_m=1.75, anchor=6)

  assert decision.valid is False and decision.reason == 'anchorIsNotALaneMarking'


def test_an_unaccounted_lane_beyond_the_anchor_is_refused():
  # A lane marking beyond the anchor means another lane exists to the right.
  extra_line = carriageway() + (boundary(7, -10.5),)
  # A lane-wide gap to the road edge means the same thing without a visible line.
  far_shoulder = tuple(replace(b, points=((0.0, -10.5), (30.0, -10.5))) if b.track_id == 6 else b
                       for b in carriageway())

  assert settle(RightEdgeAnchoredGate(), extra_line, ego_y_m=1.75).reason == 'unaccountedLaneBeyondAnchor'
  assert settle(RightEdgeAnchoredGate(), far_shoulder, ego_y_m=1.75).reason == 'unaccountedLaneBeyondAnchor'


def test_a_road_edge_between_the_ego_and_the_anchor_is_refused():
  # A drivable boundary cannot divide lanes, so it cannot sit inside the ladder.
  divider = tuple(replace(b, marking_type=LaneMarkingType.roadEdge) if b.track_id == 4 else b
                  for b in carriageway())

  assert settle(RightEdgeAnchoredGate(), divider, ego_y_m=1.75).reason == 'dividerIsNotALaneMarking'


def test_lines_left_of_the_ego_do_not_change_the_answer():
  only_right_side = tuple(b for b in carriageway() if b.track_id in (3, 4, ANCHOR, 6))

  decision = settle(RightEdgeAnchoredGate(), only_right_side, ego_y_m=1.75)

  assert decision.valid is True and decision.lane_index == 2
  # The shipped both-edge gate cannot answer on exactly this input.
  shipped = AbsoluteLaneGate().update(only_right_side, left_edge_track_id=3,
                                      right_edge_track_id=ANCHOR, frame_id=0,
                                      timestamp_ns=START_NS, session_id='session',
                                      route_revision=1, topology_state=LaneTopologyState.normal,
                                      ego_y_m=1.75)
  assert shipped.valid is False


def test_a_missing_or_double_counted_divider_is_refused():
  missing = tuple(b for b in carriageway() if b.track_id != 4)
  spurious = carriageway() + (boundary(8, -5.25),)

  assert settle(RightEdgeAnchoredGate(), missing, ego_y_m=-1.75).reason == 'implausibleLaneWidth'
  assert settle(RightEdgeAnchoredGate(), spurious, ego_y_m=-1.75).reason == 'implausibleLaneWidth'


def test_without_a_map_total_nothing_is_claimed():
  for total in (None, 0, -1, 13, True, 4.0):
    decision = settle(RightEdgeAnchoredGate(), carriageway(), ego_y_m=1.75, lane_total=total)
    assert decision.valid is False and decision.reason == 'laneTotalUnavailable', total


def test_a_total_that_contradicts_the_anchor_is_refused():
  decision = settle(RightEdgeAnchoredGate(), carriageway(), ego_y_m=5.25, lane_total=3)

  assert decision.valid is False and decision.reason == 'mapTotalInconsistent'


def test_the_anchor_must_be_observed_visible_and_confident():
  without = tuple(b for b in carriageway() if b.track_id != ANCHOR)
  invisible = tuple(replace(b, visible=False) if b.track_id == ANCHOR else b for b in carriageway())
  weak = tuple(replace(b, confidence=0.1) if b.track_id == ANCHOR else b for b in carriageway())

  assert settle(RightEdgeAnchoredGate(), without, ego_y_m=1.75).reason == 'laneAnchorNotObserved'
  assert settle(RightEdgeAnchoredGate(), invisible, ego_y_m=1.75).reason == 'anchorNotVisible'
  assert settle(RightEdgeAnchoredGate(), weak, ego_y_m=1.75).reason == 'lowConfidenceBoundary'


def test_an_interior_divider_that_is_not_visible_or_confident_is_refused():
  carried = tuple(replace(b, visible=False) if b.track_id == 3 else b for b in carriageway())
  weak = tuple(replace(b, confidence=0.1) if b.track_id == 3 else b for b in carriageway())

  assert settle(RightEdgeAnchoredGate(), carried, ego_y_m=1.75).reason == 'interiorBoundaryNotVisible'
  assert settle(RightEdgeAnchoredGate(), weak, ego_y_m=1.75).reason == 'lowConfidenceBoundary'


def test_an_ego_right_of_the_anchor_has_no_lane():
  decision = settle(RightEdgeAnchoredGate(), carriageway(), ego_y_m=-7.5)

  assert decision.valid is False and decision.reason == 'implausibleLaneWidth'


def test_merges_splits_and_ambiguity_always_refuse():
  for state in (LaneTopologyState.mergingLeft, LaneTopologyState.splittingRight,
                LaneTopologyState.ambiguous, LaneTopologyState.stale):
    decision = settle(RightEdgeAnchoredGate(), carriageway(), ego_y_m=1.75, state=state)
    assert decision.valid is False and decision.reason == f'topology:{state.name}'


def test_three_consistent_frames_sessions_and_gaps_are_required():
  gate = RightEdgeAnchoredGate()
  assert settle(gate, carriageway(), ego_y_m=1.75, frames=1).valid is False
  assert settle(gate, carriageway(), ego_y_m=1.75, frames=2).valid is False
  confirmed = settle(gate, carriageway(), ego_y_m=1.75, frames=3)
  assert confirmed.valid is True and confirmed.stable_samples == 3

  fresh = settle(gate, carriageway(), ego_y_m=1.75, session_id='other', frames=2)
  assert fresh.valid is False and fresh.stable_samples == 2

  gate2 = RightEdgeAnchoredGate()
  settle(gate2, carriageway(), ego_y_m=1.75, frames=1)
  late = settle(gate2, carriageway(), ego_y_m=1.75, frames=1, start_ns=START_NS + 900_000_000)
  assert late.valid is False and late.stable_samples == 1


def test_a_confirmed_decision_plugs_into_the_verified_producer(tmp_path):
  path = tmp_path / 'road_lane_position.json'
  decision = settle(RightEdgeAnchoredGate(), carriageway(), ego_y_m=1.75)
  assert decision.valid is True

  record = publish_decision(decision, nav_session_id='nav', route_revision=7, path=path,
                            now_ns=START_NS + 2 * STEP_NS)

  assert record['valid'] is True and record['lane_index'] == 2 and record['lane_count'] == 4
  value = lane_position_feedback(SimpleNamespace(session_id='nav', route_revision=7), path=path,
                                 now_ns=START_NS + 2 * STEP_NS)
  assert value['valid'] is True and value['laneIndex'] == 2 and value['laneCount'] == 4
