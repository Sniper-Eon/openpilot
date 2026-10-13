from types import SimpleNamespace

import pytest

from openpilot.selfdrive.car.cruise import V_CRUISE_UNSET
from openpilot.sunnypilot.navassist.speed_controller import NavigationSpeedController
from openpilot.sunnypilot.navassist.tests.test_speed_controller import FakeSM, nav
from openpilot.sunnypilot.selfdrive.controls.lib.longitudinal_backends.registry import BackendId
from openpilot.sunnypilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlannerSP, LongitudinalPlanSource


def planner(backend, *, enabled=True):
  # Exercise the real common target selection without starting processes or
  # constructing unrelated location/map services. The navigation controller is real.
  result = object.__new__(LongitudinalPlannerSP)
  result.active_backend_id = backend
  result.nav = NavigationSpeedController(enabled=enabled, require_sp_longitudinal_owner=True)
  result.scc = SimpleNamespace(
    update=lambda *args: None,
    vision=SimpleNamespace(is_active=False, output_v_target=V_CRUISE_UNSET, output_a_target=0.0),
    map=SimpleNamespace(output_v_target=V_CRUISE_UNSET, output_a_target=0.0),
  )
  result.resolver = SimpleNamespace(
    update=lambda *args: None, speed_limit_valid=False, speed_limit_last_valid=False,
    speed_limit=0.0, speed_limit_final_last=0.0, distance=0.0,
  )
  result.sla = SimpleNamespace(update=lambda *args: None, output_v_target=V_CRUISE_UNSET, output_a_target=0.0)
  result.events_sp = None
  return result


def targets(planner, *, distance=100.0, healthy=True, cruise=15.0, accel=0.1, speed=10.0):
  sm = FakeSM(nav(distance=distance), healthy=healthy)
  sm['carState'].vCruiseCluster = cruise * 3.6
  sm['carControl'] = SimpleNamespace(enabled=True, longActive=True, cruiseControl=SimpleNamespace(override=False))
  return planner.update_targets(sm, speed, accel, cruise)


@pytest.mark.parametrize('backend', list(BackendId))
def test_all_three_backends_receive_navigation_speed_ceiling_without_changing_accel_seed(backend):
  p = planner(backend)
  assert targets(p) == (15.0, 0.1)
  assert targets(p, distance=60.0) == (5.0, 0.1)
  assert p.source == LongitudinalPlanSource.navAssist


@pytest.mark.parametrize('backend', list(BackendId))
def test_all_three_backends_receive_early_turn_ceiling_above_60_kph(backend):
  p = planner(backend)
  speed = 80.0 / 3.6
  assert targets(p, distance=500, speed=speed, cruise=speed) == (speed, 0.1)
  assert targets(p, distance=230, speed=speed, cruise=speed) == (5.0, 0.1)
  assert p.source == LongitudinalPlanSource.navAssist


@pytest.mark.parametrize('backend', list(BackendId))
@pytest.mark.parametrize('enabled,healthy', [(False, True), (True, False)])
def test_inactive_navigation_preserves_common_target_exactly(backend, enabled, healthy):
  p = planner(backend, enabled=enabled)
  assert targets(p, distance=60.0, healthy=healthy, cruise=12.34567, accel=-0.4567) == (12.34567, -0.4567)
  assert p.source == LongitudinalPlanSource.cruise


@pytest.mark.parametrize('backend', list(BackendId))
def test_lower_vision_target_wins_and_navigation_remains_when_vision_releases(backend):
  p = planner(backend)
  targets(p)
  assert targets(p, distance=60.0) == (5.0, 0.1)
  p.scc.vision.is_active = True
  p.scc.vision.output_v_target = 3.0
  p.scc.vision.output_a_target = -0.4
  assert targets(p, distance=55.0) == (3.0, -0.4)
  assert p.source == LongitudinalPlanSource.sccVision
  p.scc.vision.is_active = False
  p.scc.vision.output_v_target = V_CRUISE_UNSET
  assert targets(p, distance=40.0) == (5.0, 0.1)
  assert p.source == LongitudinalPlanSource.navAssist


@pytest.mark.parametrize('backend', list(BackendId))
def test_navigation_does_not_raise_a_lower_existing_speed_target(backend):
  p = planner(backend)
  targets(p)
  targets(p, distance=60.0)
  p.sla.output_v_target = 2.0
  p.sla.output_a_target = -0.8
  assert targets(p, distance=55.0) == (2.0, -0.8)
  assert p.source == LongitudinalPlanSource.speedLimitAssist


@pytest.mark.parametrize('backend', [None, 99])
def test_unregistered_backend_is_not_implicitly_admitted(backend):
  p = planner(backend)
  targets(p)
  assert targets(p, distance=60.0) == (15.0, 0.1)
  assert not p.nav.event_admitted
