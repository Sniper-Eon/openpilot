from dataclasses import replace
from types import SimpleNamespace

from openpilot.sunnypilot.navassist.lane_intent import (
  LaneIntentDirection, LaneTopologyInput, LaneVehicleInput, NavLaneIntentCoordinator, NavLanePlan,
)
from openpilot.sunnypilot.selfdrive.controls.lib.relative_lane_consistency import RelativeLaneConsistencyFilter


def test_unknown_neighbor_never_becomes_confirmed_edge():
  observer = RelativeLaneConsistencyFilter()
  for second in (1, 10, 30):
    status = observer.update(('route', 1, 1), direction='left', neighbor_exists=None,
                             observation_valid=True, lane_change_active=False,
                             steering_pressed=False, now_ns=second * 1_000_000_000)
    assert not status.ready and not status.edge_confirmed
    assert status.reason == 'neighborUnknown'


def test_missing_outer_line_is_unknown_not_absent():
  from openpilot.sunnypilot.navassist.nav_lane_intentd import neighbor_observation
  topology = SimpleNamespace(validForControl=True, leftNeighborExists=False,
                             leftEvidenceValid=True, leftEgoSideMarking='solid')
  assert neighbor_observation(topology, side='left', healthy=True) is None
  topology.leftEgoSideMarking = 'roadEdge'
  assert neighbor_observation(topology, side='left', healthy=True) is False
  topology.leftNeighborExists = True
  topology.leftEgoSideMarking = 'dashed'
  assert neighbor_observation(topology, side='left', healthy=True) is True
  assert neighbor_observation(topology, side='left', healthy=False) is None


def setup_request():
  coordinator = NavLaneIntentCoordinator()
  plan = NavLanePlan(True, 'route', 1, 1, 3, (0,), heuristic=True, edge_direction=LaneIntentDirection.left)
  topology = LaneTopologyInput(True, 3, 1, True, True, True, True)
  vehicle = LaneVehicleInput(True, 15, left_blinker=True)
  for second in (1, 1.6, 2.2):
    intent = coordinator.update(plan, topology, vehicle, now_ns=int(second * 1e9))
  assert intent.signal_requested
  return coordinator, plan, topology, vehicle, intent.request_id


def test_short_topology_gap_keeps_lamp_and_identity_without_ready():
  coordinator, plan, topology, vehicle, request_id = setup_request()
  gap = coordinator.update(plan, replace(topology, valid_for_control=False), vehicle, now_ns=2_250_000_000)
  assert gap.signal_requested and not gap.lane_change_ready and gap.request_id == request_id
  recovering = coordinator.update(plan, topology, vehicle, now_ns=2_300_000_000)
  assert recovering.signal_requested and not recovering.lane_change_ready
  resumed = coordinator.update(plan, topology, vehicle, now_ns=2_850_000_000)
  assert resumed.signal_requested and resumed.request_id == request_id


def test_prolonged_unknown_cancels_once_then_waits_for_stable_recovery():
  coordinator, plan, topology, vehicle, request_id = setup_request()
  unknown = replace(topology, left_neighbor_exists=None)
  assert coordinator.update(plan, unknown, vehicle, now_ns=2_250_000_000).signal_requested
  assert not coordinator.update(plan, unknown, vehicle, now_ns=3_300_000_000).signal_requested
  for second in (3.4, 4, 5, 6.3):
    result = coordinator.update(plan, topology, vehicle, now_ns=int(second * 1e9))
    assert not result.signal_requested
  result = coordinator.update(plan, topology, vehicle, now_ns=6_450_000_000)
  assert result.signal_requested and result.request_id == request_id
  assert not result.lane_change_ready  # Fresh physical lamp/crossing confirmation is still required.


def test_brake_and_turn_handoff_cancel_observation_hold():
  for brake in (False, True):
    coordinator, plan, topology, vehicle, _ = setup_request()
    unknown = replace(topology, valid_for_control=False)
    coordinator.update(plan, unknown, vehicle, now_ns=2_250_000_000)
    result = coordinator.update(plan, unknown, replace(vehicle, brake_pressed=brake),
                                allow_new_lane_change=brake, now_ns=2_300_000_000)
    assert not result.signal_requested


def test_repeated_unknown_frames_do_not_accumulate_recovery_time():
  coordinator, plan, topology, vehicle, request_id = setup_request()
  unknown = replace(topology, left_neighbor_exists=None)
  coordinator.update(plan, unknown, vehicle, now_ns=2_250_000_000)
  coordinator.update(plan, unknown, vehicle, now_ns=3_300_000_000)
  for second in range(4, 15):
    assert not coordinator.update(plan, topology, vehicle, now_ns=second * 1_000_000_000).signal_requested
    result = coordinator.update(plan, unknown, vehicle, now_ns=second * 1_000_000_000 + 100_000_000)
    assert not result.signal_requested and result.request_id == request_id


def test_observation_recovery_does_not_bypass_solid_or_blindspot():
  for obstruction in ('solid', 'blindspot'):
    coordinator, plan, topology, vehicle, _ = setup_request()
    coordinator.update(plan, replace(topology, valid_for_control=False), vehicle, now_ns=2_250_000_000)
    topology = replace(topology, left_crossing_allowed=obstruction != 'solid')
    vehicle = replace(vehicle, left_blindspot=obstruction == 'blindspot')
    for second in (2.3, 2.85, 3.2, 3.6):
      assert not coordinator.update(plan, topology, vehicle, now_ns=int(second * 1e9)).lane_change_ready


def test_route_change_does_not_inherit_observation_hold():
  coordinator, plan, topology, vehicle, _ = setup_request()
  unknown = replace(topology, valid_for_control=False)
  coordinator.update(plan, unknown, vehicle, now_ns=2_250_000_000)
  result = coordinator.update(replace(plan, maneuver_event_id=2), unknown, vehicle, now_ns=2_300_000_000)
  assert not result.signal_requested and result.reason == 'routeChanged'


def test_navigation_hold_is_respected_at_actual_sp_entry():
  from openpilot.sunnypilot.selfdrive.controls.lib.tests.test_nav_lane_intent_desire import car_state, helper
  from openpilot.selfdrive.controls.lib.desire_helper import LaneChangeState
  coordinator, plan, topology, vehicle, _ = setup_request()
  desire = helper()
  for second in (2.25, 2.3, 2.35):
    request = coordinator.update(plan, replace(topology, valid_for_control=False), vehicle, now_ns=int(second * 1e9))
    wire = SimpleNamespace(valid=True, signalRequested=request.signal_requested, direction='left',
                           targetLaneIndex=request.target_lane_index, spLaneChangeReady=request.lane_change_ready)
    desire.update(car_state(leftBlinker=True), True, 1.0, nav_lane_intent=wire, left_crossing_allowed=True)
    assert desire.lane_change_state == LaneChangeState.preLaneChange
