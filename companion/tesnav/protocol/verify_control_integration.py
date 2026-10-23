"""Offline App packets -> C3 parser/publisher/native requests; never publishes to the car.

Run with the C3 Python environment and the JSON produced by
NavigationControlIntegrationTest (app/build/navassist/control-integration.json).
"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from openpilot.sunnypilot.navassist.protocol import AcceptedSnapshot, parse_snapshot
from openpilot.sunnypilot.navassist.publisher import build_nav_assist_message
from openpilot.sunnypilot.navassist.nav_lane_intentd import build_lane_plan, navigation_linked
from openpilot.sunnypilot.navassist.lane_intent import (
  LaneIntentDirection, LaneTopologyInput, LaneVehicleInput, NavLaneIntentCoordinator,
  NavTurnPlan, NavTurnSignalCoordinator,
)
from openpilot.sunnypilot.navassist.settings import NavAssistSettings
from openpilot.sunnypilot.navassist.speed_controller import NavigationSpeedController


class Inputs(dict):
  def __init__(self, nav, gas=False):
    super().__init__(navAssistStateSP=nav, carState=SimpleNamespace(gasPressed=gas, brakePressed=False))
    self.seen = self.alive = self.valid = {"navAssistStateSP": True}


def verify(packets, settings=None):
  results = []
  settings = settings or NavAssistSettings()
  for side, direction, target in (("left", LaneIntentDirection.left, 0), ("right", LaneIntentDirection.right, 2)):
    states = {}
    for phase in ("far", "near", "lost", "same-event", "recovered", "next-event", "stopped"):
      packet = parse_snapshot(json.dumps(packets[f"{side}-{phase}"], ensure_ascii=False).encode())
      accepted = AcceptedSnapshot(packet, 1_000_000_000, 2_200_000_000)
      states[phase] = build_nav_assist_message(accepted, 1_000_000_000).navAssistStateSP
      assert bool(states[phase].valid) == (phase in ("far", "near", "recovered", "next-event")), (side, phase)
      assert not build_nav_assist_message(accepted, 2_200_000_001).navAssistStateSP.valid
    far, near = states["far"], states["near"]
    topology = SimpleNamespace(visibleLaneCount=3)
    plan = build_lane_plan(far, topology, healthy=True, settings=settings)
    assert plan.valid and plan.recommended_indices == (target,)
    assert not plan.ignore_solid_boundary and not plan.allow_unknown_crossing
    lane = NavLaneIntentCoordinator()
    observed = LaneTopologyInput(True, 3, 1, True, True, True, True)
    for now in (0, 500_000_000, 1_000_000_000):
      request = lane.update(plan, observed, LaneVehicleInput(True, 10.0), now_ns=now)
    assert request.signal_requested and request.direction == direction, request
    blocked = NavLaneIntentCoordinator()
    for now in (0, 500_000_000, 1_000_000_000):
      denied = blocked.update(plan, LaneTopologyInput(True, 3, 1, True, True, False, False),
                              LaneVehicleInput(True, 10.0), now_ns=now)
    assert not denied.lane_change_ready
    car_with_lamp = LaneVehicleInput(True, 10.0, left_blinker=side == "left", right_blinker=side == "right")
    for now in (1_200_000_000, 1_600_000_000):
      ready = lane.update(plan, observed, car_with_lamp, now_ns=now)
      denied = blocked.update(plan, LaneTopologyInput(True, 3, 1, True, True, False, False),
                              car_with_lamp, now_ns=now)
    assert ready.lane_change_ready and not denied.lane_change_ready
    lane.update(build_lane_plan(states["lost"], topology, healthy=True, settings=settings), observed,
                car_with_lamp, now_ns=2_000_000_000)
    for now in (3_000_000_000, 4_000_000_000):
      resumed_lane = lane.update(plan, observed, car_with_lamp, now_ns=now)
    assert not resumed_lane.lane_change_ready and not resumed_lane.signal_requested

    speed = NavigationSpeedController(settings_provider=lambda: settings)
    def update_speed(nav, gas=False):
      speed.update(Inputs(nav, gas), long_enabled=True, long_override=False,
                   v_ego=10.0, a_ego=0.0, v_cruise=20.0, planner_verified=True)
    update_speed(far)
    assert speed.event_admitted and not speed.is_active
    update_speed(near)
    assert speed.is_active and abs(speed.output_v_target - settings.turn_speed_kph / 3.6) < 1e-6
    turn = NavTurnSignalCoordinator()
    def turn_plan(nav):
      return NavTurnPlan(navigation_linked(nav, base_healthy=True), nav.sessionId, nav.routeRevision,
                         nav.maneuverEventId, str(nav.maneuver), nav.maneuverDistanceM)
    lamp = turn.update(turn_plan(near), speed_mps=10.0, now_ns=1_000_000_000)
    assert lamp.signal_requested and lamp.direction == direction
    update_speed(states["lost"])
    assert not speed.is_active
    update_speed(near)
    assert not speed.is_active  # An interrupted active event stays cancelled.
    speed = NavigationSpeedController(settings_provider=lambda: settings)
    update_speed(far)
    update_speed(near)
    assert speed.is_active
    update_speed(near, gas=True)
    assert not speed.is_active
    update_speed(states["lost"])
    update_speed(states["recovered"])
    assert not speed.is_active  # Driver cancellation cannot resume the same turn.
    for phase in ("lost", "same-event", "stopped"):
      cancelled = states[phase]
      assert not build_lane_plan(cancelled, topology, healthy=True, settings=settings).valid
      assert not turn.update(turn_plan(cancelled), speed_mps=10.0, now_ns=3_000_000_000).signal_requested
      update_speed(cancelled)
      assert not speed.is_active
    # A far-away source outage must not suppress a later lamp request for the same turn.
    recovered_lamp = turn.update(turn_plan(states["recovered"]), speed_mps=10.0, now_ns=5_000_000_000)
    assert recovered_lamp.signal_requested and recovered_lamp.direction == direction
    assert states["recovered"].maneuverEventId == far.maneuverEventId
    speed = NavigationSpeedController(settings_provider=lambda: settings)
    update_speed(far)
    update_speed(states["lost"])
    update_speed(states["recovered"])
    assert speed.is_active  # Only an event whose braking never began may be admitted again.
    results.append({"direction": side, "laneTarget": target, "speedTargetKph": settings.turn_speed_kph,
                    "turnSignal": True, "sourceCancellation": True, "driverCancellation": True,
                    "boundaryVeto": True, "snapshotExpiry": True})
  return results


if __name__ == "__main__":
  packets = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
  # Test both native defaults and the device's current 25 kph ordinary-turn policy.
  print(json.dumps(verify(packets) + verify(packets, NavAssistSettings(turn_speed_kph=25)), indent=2))
