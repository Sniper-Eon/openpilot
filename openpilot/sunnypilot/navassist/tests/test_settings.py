from dataclasses import replace

import pytest

from openpilot.sunnypilot.navassist.settings import NavAssistSettings, SettingsCache, SettingsStore, parse_settings
from openpilot.sunnypilot.navassist.tests.test_speed_controller import FakeSM, nav, update
from openpilot.sunnypilot.navassist.speed_controller import NavigationSpeedController
from openpilot.sunnypilot.navassist.lane_intent import NavTurnPlan, NavTurnSignalCoordinator
from openpilot.sunnypilot.navassist.nav_lane_intentd import build_lane_plan
from types import SimpleNamespace
from openpilot.sunnypilot.navassist.tests.test_lane_intent import topology, vehicle
from openpilot.sunnypilot.navassist.lane_intent import NavLanePlan, NavLaneIntentCoordinator, LaneIntentDirection, ObservedLaneChangeState


def test_settings_persist_and_keep_unmodified_defaults(tmp_path):
  store = SettingsStore(tmp_path / 'settings.json')
  assert store.read() == NavAssistSettings()
  store.update({'turn_lane_lookahead_m': 300, 'turn_speed_kph': 20})
  assert SettingsStore(store.path).read() == replace(NavAssistSettings(), turn_lane_lookahead_m=300, turn_speed_kph=20)


@pytest.mark.parametrize('changes', [{'enabled': 1}, {'turn_speed_kph': 100}, {'signal_lead_time_s': 2},
                                    {'turn_lane_lookahead_m': 333}, {'unexpected': True}])
def test_invalid_values_are_rejected(changes):
  with pytest.raises(ValueError):
    parse_settings(changes)


def test_corrupt_update_keeps_last_valid_runtime_configuration(tmp_path):
  store = SettingsStore(tmp_path / 'settings.json')
  store.update({'enabled': False})
  cache = SettingsCache(store)
  assert not cache.read().enabled
  store.path.write_text('{broken')
  cache.next_read = 0
  assert not cache.read().enabled and cache.error


@pytest.mark.parametrize('field', ['enabled', 'turn_slowdown_enabled'])
def test_speed_switch_returns_original_cruise_target(field):
  settings = replace(NavAssistSettings(), **{field: False})
  controller = NavigationSpeedController(settings_provider=lambda: settings)
  update(controller, FakeSM(nav(distance=120)))
  update(controller, FakeSM(nav(distance=60)))
  assert not controller.is_active and not controller.event_admitted


def test_selected_turn_speed_is_used_by_real_cereal_message():
  settings = replace(NavAssistSettings(), turn_speed_kph=24)
  controller = NavigationSpeedController(settings_provider=lambda: settings)
  update(controller, FakeSM(nav(distance=120)))
  update(controller, FakeSM(nav(distance=50)))
  assert controller.is_active
  assert controller.output_v_target == pytest.approx(24 / 3.6)


def test_lane_distance_setting_applies_to_heuristic_and_lane_info():
  settings = replace(NavAssistSettings(), turn_lane_lookahead_m=300)
  n = SimpleNamespace(valid=True, stale=False, lanes=[], maneuver='turnLeft', maneuverDistanceM=600,
                      sessionId='x', routeRevision=1, maneuverEventId=1)
  topology = SimpleNamespace(visibleLaneCount=3)
  assert not build_lane_plan(n, topology, healthy=True, settings=settings).recommended_indices
  n.lanes = [SimpleNamespace(index=0, recommended=True)]
  assert not build_lane_plan(n, topology, healthy=True, settings=settings).valid
  n.maneuverDistanceM = 200
  assert build_lane_plan(n, topology, healthy=True, settings=settings).valid
  assert not build_lane_plan(n, topology, healthy=True, settings=replace(settings, lane_change_enabled=False)).valid


def test_signal_time_setting_changes_the_request_window():
  plan = NavTurnPlan(True, 'x', 1, 1, 'turnLeft', 100)
  assert not NavTurnSignalCoordinator().update(plan, speed_mps=10, now_ns=1, lookahead_time_s=3).signal_requested
  assert NavTurnSignalCoordinator().update(plan, speed_mps=10, now_ns=1, lookahead_time_s=10).signal_requested


def test_configured_change_count_stops_next_request_after_completed_cycle():
  coordinator = NavLaneIntentCoordinator(max_changes=1)
  plan = NavLanePlan(True, 'session-a', 1, 7, 3, (0,), heuristic=True)
  topo = topology(ego=1, left_cross=True)
  for now in (0, 500_000_000, 1_000_000_000):
    result = coordinator.update(plan, topo, vehicle(), now_ns=now)
  assert result.signal_requested
  coordinator.update(plan, topo, vehicle(left_blinker=True, state=ObservedLaneChangeState.starting,
                                        direction=LaneIntentDirection.left), now_ns=1_500_000_000)
  coordinator.update(plan, topo, vehicle(left_blinker=True), now_ns=2_000_000_000)
  completed = coordinator.update(plan, topo, vehicle(left_blinker=True), now_ns=2_600_000_000)
  assert not completed.signal_requested
  coordinator.update(plan, topo, vehicle(), now_ns=4_000_000_000)
  result = coordinator.update(plan, topo, vehicle(), now_ns=7_000_000_000)
  assert not result.signal_requested and result.reason == 'heuristicChangeLimit'
