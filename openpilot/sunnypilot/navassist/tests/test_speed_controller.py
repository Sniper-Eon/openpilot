from types import SimpleNamespace

import pytest

from openpilot.cereal import custom
from opendbc.sunnypilot.car.tesla.values import TeslaFlagsSP
from openpilot.selfdrive.car.cruise import V_CRUISE_UNSET
from openpilot.sunnypilot.navassist.speed_controller import MIN_TARGET_SPEED_MPS, NavigationSpeedController


class FakeSM(dict):
  def __init__(self, nav, *, gas=False, brake=False, healthy=True, tesla_flags=0):
    super().__init__(
      navAssistStateSP=nav,
      carState=SimpleNamespace(gasPressed=gas, brakePressed=brake),
      carStateSP=SimpleNamespace(flags=tesla_flags),
    )
    self.seen = {"navAssistStateSP": healthy, "carStateSP": healthy}
    self.alive = {"navAssistStateSP": healthy, "carStateSP": healthy}
    self.valid = {"navAssistStateSP": healthy, "carStateSP": healthy}


def nav(*, distance=100.0, event_id=1, valid=True, stale=False, advisory=None,
        maneuver=custom.NavAssistStateSP.Maneuver.turnRight):
  return custom.NavAssistStateSP.new_message(
    valid=valid,
    stale=stale,
    maneuver=maneuver,
    maneuverDistanceM=distance,
    maneuverEventId=event_id,
    sessionId="session-a",
    routeRevision=1,
    advisorySpeedValid=advisory is not None,
    advisorySpeedMps=advisory or 0.0,
  )


def update(controller, sm, *, v_ego=10.0, v_cruise=20.0, override=False, long_enabled=True, planner_verified=True):
  controller.update(sm, long_enabled=long_enabled, long_override=override,
                    v_ego=v_ego, a_ego=0.0, v_cruise=v_cruise, planner_verified=planner_verified)


def test_disabled_controller_is_exactly_transparent_without_nav_service_state():
  controller = NavigationSpeedController(enabled=False)
  sm = FakeSM(nav(), healthy=False)
  update(controller, sm)
  assert controller.output_v_target == V_CRUISE_UNSET
  assert controller.output_a_target == 0.0
  assert not controller.is_active


def test_controller_defaults_to_automatic_activation_when_navigation_is_valid():
  controller = NavigationSpeedController()
  update(controller, FakeSM(nav(distance=100.0)))
  assert controller.enabled
  assert controller.event_admitted


def test_early_event_is_admitted_then_activates_inside_comfort_window():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=100.0)))
  assert controller.event_admitted and not controller.is_active
  assert controller.output_v_target == V_CRUISE_UNSET

  update(controller, FakeSM(nav(distance=60.0)))
  assert controller.is_active
  assert controller.output_v_target == pytest.approx(5.0)
  assert controller.output_a_target == 0.0


def test_navigation_lane_change_without_a_turn_never_contributes_a_speed_ceiling():
  controller = NavigationSpeedController(enabled=True)
  sm = FakeSM(nav(distance=60.0, maneuver=custom.NavAssistStateSP.Maneuver.mergeRight))
  update(controller, sm)
  assert not controller.is_active
  assert controller.output_v_target == V_CRUISE_UNSET
  assert not controller.event_rejected


def test_imminent_turn_deceleration_is_independent_of_lane_alignment_state():
  controller = NavigationSpeedController(enabled=True)
  sm = FakeSM(nav(distance=100.0))
  update(controller, sm)
  assert controller.output_v_target == V_CRUISE_UNSET
  assert controller.event_admitted and not controller.is_active

  update(controller, FakeSM(nav(distance=60.0)))
  assert controller.is_active
  assert controller.output_v_target == pytest.approx(5.0)


def test_admitted_turn_holds_navigation_ceiling_at_zero_distance_until_event_changes():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=100.0)))
  update(controller, FakeSM(nav(distance=60.0)))
  assert controller.is_active

  update(controller, FakeSM(nav(distance=0.0)))

  assert controller.is_active
  assert controller.output_v_target == pytest.approx(5.0)


def test_next_route_event_does_not_inherit_previous_turn_activation():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=100.0)))
  update(controller, FakeSM(nav(distance=60.0)))
  assert controller.is_active

  update(controller, FakeSM(nav(distance=500.0, event_id=2)))
  assert controller.event_admitted and not controller.event_activated
  assert not controller.is_active
  assert controller.is_releasing
  assert controller.output_v_target > 5.0


def test_late_event_is_rejected_for_its_full_lifetime():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=40.0)))
  assert controller.event_rejected and not controller.is_active
  update(controller, FakeSM(nav(distance=20.0)))
  assert controller.event_rejected and controller.output_v_target == V_CRUISE_UNSET


def test_source_loss_or_driver_override_cancels_and_latches_event():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=100.0)))
  update(controller, FakeSM(nav(distance=60.0)))
  assert controller.is_active

  update(controller, FakeSM(nav(distance=55.0), healthy=False))
  assert not controller.is_active and controller.is_releasing and controller.event_rejected
  released_target = controller.output_v_target

  update(controller, FakeSM(nav(distance=50.0)))
  assert not controller.is_active
  assert controller.output_v_target > released_target

  next_event = FakeSM(nav(distance=100.0, event_id=2))
  update(controller, next_event, override=True)
  assert not controller.is_active


def test_phone_advisory_is_bounded_and_never_requests_a_stop():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=100.0, advisory=0.5)))
  update(controller, FakeSM(nav(distance=60.0, advisory=0.5)))
  assert controller.output_v_target >= MIN_TARGET_SPEED_MPS


def test_merge_signal_never_creates_a_navigation_speed_target():
  controller = NavigationSpeedController(enabled=True)
  merge = nav(distance=80.0, maneuver=custom.NavAssistStateSP.Maneuver.mergeRight)
  update(controller, FakeSM(merge))
  assert not controller.is_active
  assert controller.output_v_target == V_CRUISE_UNSET


def test_disengaging_rejects_the_current_event_until_a_new_event_arrives():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=100.0)))
  update(controller, FakeSM(nav(distance=60.0)))
  assert controller.is_active
  update(controller, FakeSM(nav(distance=55.0)), long_enabled=False)
  assert controller.event_rejected and not controller.is_active
  update(controller, FakeSM(nav(distance=50.0)))
  assert not controller.is_active


def test_speed_increase_that_makes_comfort_deceleration_late_rejects_event():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=120.0)), v_ego=10.0)
  assert controller.event_admitted
  update(controller, FakeSM(nav(distance=60.0)), v_ego=15.0)
  assert controller.event_rejected and not controller.is_active


def test_started_deceleration_keeps_its_ceiling_as_distance_is_consumed():
  controller = NavigationSpeedController()
  update(controller, FakeSM(nav(distance=120.0)), v_ego=13.0)
  update(controller, FakeSM(nav(distance=90.0)), v_ego=13.0)
  assert controller.is_active
  # Real route distance advances in steps while the planner is still ramping
  # braking. Reapplying initial admission here used to revoke the active cap.
  for distance in (65.0, 40.0, 15.0, 0.0):
    update(controller, FakeSM(nav(distance=distance)), v_ego=12.5)
    assert controller.is_active and not controller.event_rejected
    assert controller.output_v_target == pytest.approx(5.0)


def test_disappearing_maneuver_cannot_reactivate_same_event():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=100.0)))
  update(controller, FakeSM(nav(distance=60.0)))
  assert controller.is_active
  no_event = nav(distance=55.0, event_id=0)
  no_event.maneuver = custom.NavAssistStateSP.Maneuver.none
  update(controller, FakeSM(no_event))
  assert controller.event_rejected and not controller.is_active


def test_route_can_be_started_before_sp_takes_longitudinal_ownership():
  controller = NavigationSpeedController(enabled=True, require_sp_longitudinal_owner=True)
  stock = FakeSM(nav(distance=100.0), tesla_flags=int(TeslaFlagsSP.STOCK_LONGITUDINAL_ACTIVE))
  update(controller, stock)
  assert not controller.event_rejected and not controller.event_admitted and controller.output_v_target == V_CRUISE_UNSET

  # The same still-early event may be admitted after SP takes ownership.
  sp = FakeSM(nav(distance=100.0), tesla_flags=0)
  update(controller, sp)
  assert controller.event_admitted


@pytest.mark.parametrize("flags", [
  TeslaFlagsSP.DYNAMIC_STOCK_ACTIVE,
  TeslaFlagsSP.MANUAL_STOCK_ACTIVE,
  TeslaFlagsSP.AP_HYBRID_ACTIVE | TeslaFlagsSP.STOCK_LONGITUDINAL_ACTIVE,
])
def test_all_tesla_stock_ownership_modes_fail_closed(flags):
  controller = NavigationSpeedController(enabled=True, require_sp_longitudinal_owner=True)
  update(controller, FakeSM(nav(distance=100.0), tesla_flags=int(flags)))
  assert not controller.event_admitted and not controller.is_active
  assert controller.output_v_target == V_CRUISE_UNSET


def test_tesla_ap_hybrid_sp_owner_is_allowed():
  controller = NavigationSpeedController(enabled=True, require_sp_longitudinal_owner=True)
  flags = int(TeslaFlagsSP.AP_HYBRID_ACTIVE)
  update(controller, FakeSM(nav(distance=100.0), tesla_flags=flags))
  assert controller.event_admitted


def test_route_can_be_started_before_supported_longitudinal_backend_is_selected():
  controller = NavigationSpeedController(enabled=True)
  update(controller, FakeSM(nav(distance=100.0)), planner_verified=False)
  assert not controller.event_rejected and controller.output_v_target == V_CRUISE_UNSET
  update(controller, FakeSM(nav(distance=90.0)), planner_verified=True)
  assert controller.event_admitted and not controller.event_rejected


def test_disengaging_before_braking_pauses_then_reassesses_same_event():
  controller = NavigationSpeedController(enabled=True)
  sm = FakeSM(nav(distance=100.0))
  update(controller, sm)
  assert controller.event_admitted
  update(controller, FakeSM(nav(distance=90.0)), long_enabled=False)
  assert not controller.event_rejected and not controller.event_admitted
  update(controller, FakeSM(nav(distance=80.0)), long_enabled=True)
  assert controller.event_admitted and not controller.event_rejected


@pytest.mark.parametrize("speed_kph", [65.3, 80.0, 100.0, 145.0])
def test_navigation_brakes_from_normal_cruise_speeds_when_distance_is_sufficient(speed_kph):
  controller = NavigationSpeedController()
  speed = speed_kph / 3.6
  required = controller._required_distance(speed, 5.0)
  update(controller, FakeSM(nav(distance=required + 60)), v_ego=speed, v_cruise=speed)
  assert controller.event_admitted
  update(controller, FakeSM(nav(distance=required + 15)), v_ego=speed, v_cruise=speed)
  assert controller.is_active and controller.output_v_target == pytest.approx(5.0)


@pytest.mark.parametrize("speed", [float("nan"), float("inf"), -1.0, 150 / 3.6])
def test_invalid_or_out_of_cruise_range_speed_does_not_admit_navigation(speed):
  controller = NavigationSpeedController()
  update(controller, FakeSM(nav(distance=1_000)), v_ego=speed)
  assert not controller.is_active and not controller.event_admitted


def test_previous_turn_driver_override_does_not_poison_next_turn_8970m_away():
  controller = NavigationSpeedController()
  update(controller, FakeSM(nav(distance=100, event_id=1)))
  update(controller, FakeSM(nav(distance=60, event_id=1)))
  assert controller.is_active
  # Recorded pattern: navigation advances before the driver finishes the turn.
  update(controller, FakeSM(nav(distance=8970, event_id=2), brake=True), long_enabled=False)
  assert not controller.is_active
  assert controller.event_key[-1] == 1
  update(controller, FakeSM(nav(distance=1_000, event_id=2)), v_ego=80 / 3.6)
  assert controller.event_admitted and not controller.event_rejected
  update(controller, FakeSM(nav(distance=240, event_id=2)), v_ego=80 / 3.6)
  assert controller.is_active


@pytest.mark.parametrize("unavailable", ["nav", "gas", "owner", "backend"])
def test_pre_braking_interruptions_recheck_distance_without_latching_future_event(unavailable):
  controller = NavigationSpeedController(require_sp_longitudinal_owner=True)
  update(controller, FakeSM(nav(distance=500)))
  interrupted = FakeSM(nav(distance=400), healthy=unavailable != "nav", gas=unavailable == "gas",
                       tesla_flags=int(TeslaFlagsSP.STOCK_LONGITUDINAL_ACTIVE) if unavailable == "owner" else 0)
  update(controller, interrupted, planner_verified=unavailable != "backend")
  assert not controller.is_active and not controller.event_rejected
  update(controller, FakeSM(nav(distance=100)))
  update(controller, FakeSM(nav(distance=60)))
  assert controller.is_active


def test_recovery_that_is_already_too_late_does_not_force_hard_braking():
  controller = NavigationSpeedController()
  update(controller, FakeSM(nav(distance=500)), v_ego=15)
  update(controller, FakeSM(nav(distance=200), healthy=False), v_ego=15)
  update(controller, FakeSM(nav(distance=10)), v_ego=15)
  assert not controller.is_active and controller.event_rejected
