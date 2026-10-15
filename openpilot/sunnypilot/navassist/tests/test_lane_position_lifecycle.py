"""The producer lifecycle: confirm, then actively clear on every loss of evidence.

These tests run the real gate, the real record writer and the real reader
together. They exist because the dangerous failure is silent: if a producer
simply stops writing when it becomes unsure, the phone keeps showing the previous
lane number until the reader's deadline happens to expire it. None of that needs
real imagery to check, so it is checked here rather than deferred.
"""
from types import SimpleNamespace

from openpilot.sunnypilot.lane_topology.absolute_lane import AbsoluteLaneGate
from openpilot.sunnypilot.lane_topology.types import LaneBoundary, LaneMarkingType, LaneTopologyState
from openpilot.sunnypilot.navassist.position_feedback import lane_position_feedback
from openpilot.sunnypilot.navassist.road_lane_position import publish_decision

SESSION = 'nav-session-1'
ROUTE = 4
START_NS = 1_000_000_000
STEP_NS = 100_000_000
# The third frame, which is the earliest one that can confirm three stable samples.
CONFIRMED_NS = START_NS + 2 * STEP_NS


def boundary(track_id: int, y: float, marking_type: LaneMarkingType) -> LaneBoundary:
  return LaneBoundary(track_id, ((0.0, y), (30.0, y)), marking_type, 0.9)


def carriageway() -> tuple[LaneBoundary, ...]:
  """A three lane carriageway: left road edge, two dividers, right road edge."""
  return (
    boundary(10, 5.25, LaneMarkingType.roadEdge),
    boundary(11, 1.75, LaneMarkingType.dashed),
    boundary(12, -1.75, LaneMarkingType.dashed),
    boundary(13, -5.25, LaneMarkingType.roadEdge),
  )


def drive(gate: AbsoluteLaneGate, *, count: int, start_ns: int, session_id: str = SESSION,
          route_revision: int = ROUTE, ego_y_m: float = 0.0):
  decisions = []
  for step in range(count):
    decisions.append(gate.update(
      carriageway(), left_edge_track_id=10, right_edge_track_id=13, frame_id=step,
      timestamp_ns=start_ns + step * STEP_NS, session_id=session_id, route_revision=route_revision,
      topology_state=LaneTopologyState.normal, ego_y_m=ego_y_m,
    ))
  return decisions


def publish(decision, path, *, now_ns: int, session_id: str = SESSION, route_revision: int = ROUTE):
  return publish_decision(decision, nav_session_id=session_id, route_revision=route_revision,
                          path=path, now_ns=now_ns)


def read(path, *, now_ns: int, session_id: str = SESSION, route_revision: int = ROUTE):
  return lane_position_feedback(SimpleNamespace(session_id=session_id, route_revision=route_revision),
                                path=path, now_ns=now_ns)


def test_a_confirmed_decision_reaches_the_reader_with_its_own_age(tmp_path):
  path = tmp_path / 'road_lane_position.json'
  confirmed = drive(AbsoluteLaneGate(), count=3, start_ns=START_NS)[-1]
  assert confirmed.valid is True

  record = publish(confirmed, path, now_ns=CONFIRMED_NS)

  assert record['valid'] is True and record['lane_index'] == 2 and record['lane_count'] == 3
  value = read(path, now_ns=CONFIRMED_NS)
  assert value['valid'] is True and value['laneIndex'] == 2 and value['laneCount'] == 3
  assert value['ageMs'] == 0


def test_a_lane_change_clears_the_number_instead_of_leaving_the_old_one(tmp_path):
  path = tmp_path / 'road_lane_position.json'
  gate = AbsoluteLaneGate()
  publish(drive(gate, count=3, start_ns=START_NS)[-1], path, now_ns=CONFIRMED_NS)
  assert read(path, now_ns=CONFIRMED_NS)['valid'] is True

  # The ego moves one lane left, so the gate has to re-earn three frames.
  moving = drive(gate, count=1, start_ns=START_NS + 300_000_000, ego_y_m=3.5)[-1]
  assert moving.valid is False
  publish(moving, path, now_ns=START_NS + 300_000_000)

  # Not "stale but still valid": the previous index has to be gone immediately.
  assert read(path, now_ns=START_NS + 300_000_000)['valid'] is False


def test_a_route_change_clears_well_inside_the_reader_lifetime(tmp_path):
  path = tmp_path / 'road_lane_position.json'
  gate = AbsoluteLaneGate()
  publish(drive(gate, count=3, start_ns=START_NS)[-1], path, now_ns=CONFIRMED_NS)

  # A new route revision resets the evidence window.
  reset = drive(gate, count=1, start_ns=START_NS + 300_000_000, route_revision=ROUTE + 1)[-1]
  assert reset.valid is False and reset.stable_samples == 1
  record = publish(reset, path, now_ns=START_NS + 300_000_000, route_revision=ROUTE + 1)

  # The producer itself dropped the index, so this is not merely the reader
  # rejecting a revision mismatch.
  assert record['lane_index'] is None and record['absolute_confirmed'] is False
  assert read(path, now_ns=START_NS + 400_000_000, route_revision=ROUTE + 1)['valid'] is False


def test_a_new_navigation_session_cannot_inherit_the_previous_number(tmp_path):
  path = tmp_path / 'road_lane_position.json'
  gate = AbsoluteLaneGate()
  publish(drive(gate, count=3, start_ns=START_NS)[-1], path, now_ns=CONFIRMED_NS)

  # Even before the producer notices, the reader refuses another session.
  assert read(path, now_ns=CONFIRMED_NS, session_id='other-session')['valid'] is False

  fresh = drive(gate, count=1, start_ns=START_NS + 300_000_000, session_id='other-session')[-1]
  publish(fresh, path, now_ns=START_NS + 300_000_000, session_id='other-session')

  assert read(path, now_ns=START_NS + 300_000_000, session_id='other-session')['valid'] is False
  assert read(path, now_ns=START_NS + 300_000_000)['valid'] is False


def test_a_vanished_producer_expires_without_any_further_write(tmp_path):
  path = tmp_path / 'road_lane_position.json'
  publish(drive(AbsoluteLaneGate(), count=3, start_ns=START_NS)[-1], path, now_ns=CONFIRMED_NS)

  assert read(path, now_ns=CONFIRMED_NS)['valid'] is True
  # The producer stops writing and the file keeps the confirmation.
  assert read(path, now_ns=CONFIRMED_NS + 2_500_000_000)['valid'] is False


def test_an_already_expired_confirmation_is_downgraded_not_published_stale(tmp_path):
  path = tmp_path / 'road_lane_position.json'
  confirmed = drive(AbsoluteLaneGate(), count=3, start_ns=START_NS)[-1]
  assert confirmed.valid is True

  record = publish(confirmed, path, now_ns=CONFIRMED_NS + 5_000_000_000)

  assert record['valid'] is False and record['lane_index'] is None
  assert read(path, now_ns=CONFIRMED_NS + 5_000_000_000)['valid'] is False


def test_uncertain_decisions_keep_writing_so_nothing_is_left_behind(tmp_path):
  path = tmp_path / 'road_lane_position.json'
  gate = AbsoluteLaneGate()

  # Two frames cannot answer, and they must still be published as unknown.
  for step, decision in enumerate(drive(gate, count=2, start_ns=START_NS)):
    assert decision.valid is False
    record = publish(decision, path, now_ns=START_NS + step * STEP_NS)
    assert record['valid'] is False and record['absolute_confirmed'] is False
    assert read(path, now_ns=START_NS + step * STEP_NS)['valid'] is False
