"""Offline production App packets -> C3 ramp plan and lamp/readiness decisions.

Run in the C3 Python environment with app/build/navassist/ramp-integration.json.
Does not publish messages or command a vehicle.
"""
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from openpilot.sunnypilot.navassist.protocol import AcceptedSnapshot, parse_snapshot
from openpilot.sunnypilot.navassist.publisher import build_nav_assist_message
from openpilot.sunnypilot.navassist.nav_lane_intentd import build_lane_plan
from openpilot.sunnypilot.navassist.lane_intent import (
  LaneIntentDirection, LaneTopologyInput, LaneVehicleInput, NavLaneIntentCoordinator,
  NavTurnPlan, NavTurnSignalCoordinator,
)
from openpilot.sunnypilot.navassist.speed_controller import NavigationSpeedController


def verify(packets):
  for name, packet in packets.items():
    road_type, side, distance = name.split('-')
    direction = LaneIntentDirection.left if side == 'left' else LaneIntentDirection.right
    parsed = parse_snapshot(json.dumps(packet).encode())
    nav = build_nav_assist_message(AcceptedSnapshot(parsed, 1_000_000_000, 2_000_000_000),
                                  1_000_000_000).navAssistStateSP
    assert nav.valid and nav.roadClass == 7 and len(nav.lanes) == 0, name
    assert str(nav.maneuver) == ('exit' if road_type == '9' else 'ramp') + side.title(), name
    plan = build_lane_plan(nav, SimpleNamespace(visibleLaneCount=3), healthy=True)
    assert plan.valid and plan.edge_direction == direction, name
    assert not plan.force_fork, name  # Ordinary-road approach is not a final fork.
    nav.roadClass = 6
    highway_plan = build_lane_plan(nav, SimpleNamespace(visibleLaneCount=3), healthy=True)
    assert highway_plan.force_fork == (int(distance) == 50), name
    nav.roadClass = 7
    assert not plan.ignore_solid_boundary and not plan.allow_unknown_crossing, name
    assert NavigationSpeedController._target_for(nav) is None, name

    turn = NavTurnSignalCoordinator().update(
      NavTurnPlan(True, str(nav.sessionId), int(nav.routeRevision), int(nav.maneuverEventId),
                  str(nav.maneuver), float(distance)), speed_mps=25., now_ns=0)
    assert turn.signal_requested == (int(distance) == 50), name
    if turn.signal_requested:
      assert turn.direction == direction, name

    observed = LaneTopologyInput(True, 3, 1, True, True, True, True)
    car = LaneVehicleInput(True, 25.)
    coordinator = NavLaneIntentCoordinator()
    for stamp in (0, 500_000_000, 1_000_000_000):
      intent = coordinator.update(plan, observed, car, now_ns=stamp)
    assert intent.signal_requested and not intent.lane_change_ready, name
    car = replace(car, left_blinker=side == 'left', right_blinker=side == 'right')
    for stamp in (1_100_000_000, 1_500_000_000):
      intent = coordinator.update(plan, observed, car, now_ns=stamp)
    assert intent.lane_change_ready and intent.direction == direction, name
    blocked = replace(observed, left_crossing_allowed=False, right_crossing_allowed=False)
    assert not coordinator.update(plan, blocked, car, now_ns=1_600_000_000).lane_change_ready, name
  return len(packets)


if __name__ == '__main__':
  count = verify(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
  print(f'PASS: {count} App ramp/exit packets through native C3 plan and lamp/readiness chain')
