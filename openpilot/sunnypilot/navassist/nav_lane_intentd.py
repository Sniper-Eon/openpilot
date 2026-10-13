#!/usr/bin/env python3
from __future__ import annotations

import math
import time

from openpilot.cereal import messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.sunnypilot.navassist.lane_intent import (
  LaneIntentDirection,
  LaneTopologyInput,
  LaneVehicleInput,
  NavLaneIntent,
  NavLaneIntentCoordinator,
  NavLanePlan,
  NavTurnPlan,
  NavTurnSignalCoordinator,
  ObservedLaneChangeState,
)
from openpilot.sunnypilot.selfdrive.controls.lib.nav_turn_completion import sp_turn_geometry_active
from openpilot.sunnypilot.selfdrive.controls.lib.lane_change_blocker import lane_topology_nav_crossing_allowed
from openpilot.sunnypilot.navassist.settings import NavAssistSettings, SettingsCache


PUBLISH_HZ = 20
BASE_SERVICES = ("navAssistStateSP", "carState", "carControl", "controlsState")
LANE_SERVICES = ("laneTopologyStateSP", "modelV2")
SERVICES = BASE_SERVICES + LANE_SERVICES
TURN_LANE_LOOKAHEAD_M = 1_000.0
EXIT_LANE_LOOKAHEAD_M = 2_000.0
LEFT_TURN_LANE_MANEUVERS = frozenset(("turnLeft", "sharpLeft", "uTurnLeft"))
RIGHT_TURN_LANE_MANEUVERS = frozenset(("turnRight", "sharpRight", "uTurnRight"))
LEFT_EXIT_LANE_MANEUVERS = frozenset(("exitLeft", "rampLeft", "mergeLeft"))
RIGHT_EXIT_LANE_MANEUVERS = frozenset(("exitRight", "rampRight", "mergeRight"))
FORK_NOW_DISTANCE_M = 50.0


def selected_services_healthy(sm, services: tuple[str, ...]) -> bool:
  return all(sm.seen[service] and sm.alive[service] and sm.valid[service] for service in services)


def navigation_linked(nav, *, base_healthy: bool) -> bool:
  return bool(
    base_healthy and not nav.stale and nav.routeActive and nav.routeMatched
    and str(nav.mode) == "realtime" and int(nav.maneuverEventId) != 0
  )


def neighbor_observation(topology, *, side: str, healthy: bool) -> bool | None:
  """Visible lane / confirmed road boundary / unknown, without a schema change."""
  if side not in ("left", "right"):
    raise ValueError("side must be left or right")
  if not healthy or not topology.validForControl:
    return None
  road_edge = (bool(getattr(topology, f"{side}EvidenceValid")) and
               str(getattr(topology, f"{side}EgoSideMarking")) == "roadEdge")
  if road_edge:
    return False
  return True if getattr(topology, f"{side}NeighborExists") else None


def build_lane_plan(nav, topology, *, healthy: bool, settings: NavAssistSettings | None = None) -> NavLanePlan:
  settings = settings if settings is not None else NavAssistSettings()
  nav_valid = bool(healthy and nav.valid and not nav.stale and settings.enabled and settings.lane_change_enabled)
  lanes = tuple(nav.lanes)
  recommended = tuple(int(lane.index) for lane in lanes if lane.recommended)
  maneuver = str(nav.maneuver)
  distance_m = float(nav.maneuverDistanceM)
  lane_count = int(topology.visibleLaneCount)
  fallback_side = None
  lookahead_m = 0.0
  if maneuver in LEFT_TURN_LANE_MANEUVERS:
    fallback_side, lookahead_m = "left", settings.turn_lane_lookahead_m
  elif maneuver in RIGHT_TURN_LANE_MANEUVERS:
    fallback_side, lookahead_m = "right", settings.turn_lane_lookahead_m
  elif maneuver in LEFT_EXIT_LANE_MANEUVERS:
    fallback_side, lookahead_m = "left", settings.exit_lane_lookahead_m
  elif maneuver in RIGHT_EXIT_LANE_MANEUVERS:
    fallback_side, lookahead_m = "right", settings.exit_lane_lookahead_m
  fork_now = bool(
    maneuver in LEFT_EXIT_LANE_MANEUVERS | RIGHT_EXIT_LANE_MANEUVERS
    and math.isfinite(distance_m) and 0.0 < distance_m <= FORK_NOW_DISTANCE_M
  )

  if lanes:
    amap_lane_count = len(lanes)
    edge_recommended = bool(
      (fallback_side == "left" and 0 in recommended)
      or (fallback_side == "right" and amap_lane_count - 1 in recommended)
    )
    if nav_valid and edge_recommended and math.isfinite(distance_m) and 0.0 <= distance_m <= lookahead_m:
      target = 0 if fallback_side == "left" else max(0, lane_count - 1)
      return NavLanePlan(
        True, str(nav.sessionId), int(nav.routeRevision), int(nav.maneuverEventId),
        lane_count, (target,), heuristic=True,
        edge_direction=LaneIntentDirection.left if fallback_side == "left" else LaneIntentDirection.right,
        force_fork=fork_now, allow_unknown_crossing=True, ignore_solid_boundary=fork_now,
      )
    # AMap lane indices describe the complete road while modelV2 exposes only a
    # local visible window. Without an edge-qualified directional target there
    # is no common absolute index, so retain the observation but do not control.
    return NavLanePlan(
      False, str(nav.sessionId), int(nav.routeRevision), int(nav.maneuverEventId), amap_lane_count, (),
    )

  heuristic_valid = bool(
    nav_valid and int(nav.maneuverEventId) != 0 and fallback_side is not None
    and math.isfinite(distance_m) and 0.0 <= distance_m <= lookahead_m
  )
  if heuristic_valid:
    target = 0 if fallback_side == "left" else max(0, lane_count - 1)
    return NavLanePlan(
      True, str(nav.sessionId), int(nav.routeRevision), int(nav.maneuverEventId), lane_count, (target,), heuristic=True,
      edge_direction=LaneIntentDirection.left if fallback_side == "left" else LaneIntentDirection.right,
      force_fork=fork_now, allow_unknown_crossing=True, ignore_solid_boundary=fork_now,
    )

  return NavLanePlan(
    nav_valid, str(nav.sessionId), int(nav.routeRevision), int(nav.maneuverEventId), len(lanes), recommended,
  )


def lane_alignment_may_start(nav, turn_intent: NavLaneIntent) -> bool:
  distance_m = float(nav.maneuverDistanceM)
  approaching_turn = bool(
    turn_intent.signal_requested and str(nav.maneuver) in LEFT_TURN_LANE_MANEUVERS | RIGHT_TURN_LANE_MANEUVERS
  )
  return math.isfinite(distance_m) and distance_m > 0.0 and not approaching_turn


def main() -> None:
  settings_cache = SettingsCache()
  coordinator = NavLaneIntentCoordinator(max_changes=settings_cache.read().max_lane_changes)
  turn_signal_coordinator = NavTurnSignalCoordinator()
  sm = messaging.SubMaster(list(SERVICES), poll="navAssistStateSP")
  pm = messaging.PubMaster(["navLaneIntentSP"])
  ratekeeper = Ratekeeper(PUBLISH_HZ)
  while True:
    sm.update(50)
    base_healthy = selected_services_healthy(sm, BASE_SERVICES)
    lane_services_healthy = selected_services_healthy(sm, LANE_SERVICES)
    healthy = base_healthy and lane_services_healthy
    nav = sm["navAssistStateSP"]
    settings = settings_cache.read()
    topology = sm["laneTopologyStateSP"]
    car_state = sm["carState"]
    car_control = sm["carControl"]
    model_meta = sm["modelV2"].meta
    # A brief lane-observation gap is not a navigation outage or a loss of
    # actual lateral control. The coordinator bounds it with its existing grace.
    plan = build_lane_plan(nav, topology, healthy=base_healthy, settings=settings)
    topology_input = LaneTopologyInput(
      valid_for_control=bool(healthy and topology.validForControl),
      visible_lane_count=int(topology.visibleLaneCount),
      ego_lane_index=int(topology.egoLaneIndexFromLeft),
      left_neighbor_exists=neighbor_observation(topology, side="left", healthy=lane_services_healthy),
      right_neighbor_exists=neighbor_observation(topology, side="right", healthy=lane_services_healthy),
      left_crossing_allowed=lane_topology_nav_crossing_allowed(
        topology, side="left", healthy=lane_services_healthy,
        allow_unknown=plan.edge_direction == LaneIntentDirection.left and plan.allow_unknown_crossing,
        ignore_solid=plan.edge_direction == LaneIntentDirection.left and plan.ignore_solid_boundary,
      ),
      right_crossing_allowed=lane_topology_nav_crossing_allowed(
        topology, side="right", healthy=lane_services_healthy,
        allow_unknown=plan.edge_direction == LaneIntentDirection.right and plan.allow_unknown_crossing,
        ignore_solid=plan.edge_direction == LaneIntentDirection.right and plan.ignore_solid_boundary,
      ),
    )
    vehicle = LaneVehicleInput(
      lateral_active=bool(base_healthy and car_control.latActive),
      speed_mps=float(car_state.vEgo),
      left_blindspot=bool(car_state.leftBlindspot),
      right_blindspot=bool(car_state.rightBlindspot),
      left_blinker=bool(car_state.leftBlinker),
      right_blinker=bool(car_state.rightBlinker),
      brake_pressed=bool(car_state.brakePressed),
      gas_pressed=bool(car_state.gasPressed),
      steering_pressed=bool(car_state.steeringPressed),
      lane_change_state=ObservedLaneChangeState(int(model_meta.laneChangeState.raw)),
      lane_change_direction=LaneIntentDirection(int(model_meta.laneChangeDirection.raw)),
    )
    now_ns = time.monotonic_ns()
    turn_plan = NavTurnPlan(
      valid=navigation_linked(nav, base_healthy=base_healthy),
      session_id=str(nav.sessionId),
      route_revision=int(nav.routeRevision),
      maneuver_event_id=int(nav.maneuverEventId),
      maneuver=str(nav.maneuver),
      distance_m=float(nav.maneuverDistanceM),
    )
    turn_intent = turn_signal_coordinator.update(
      turn_plan, speed_mps=float(car_state.vEgo), now_ns=now_ns,
      turn_geometry_active=sp_turn_geometry_active(sm["controlsState"], float(car_state.vEgo)),
      lookahead_time_s=settings.signal_lead_time_s,
    )
    # Reuse the existing pre-turn window. An SP change already in progress
    # finishes before handoff; a further approach-lane change must not suppress
    # the model's turn desire at the intersection.
    lane_intent = coordinator.update(
      plan, topology_input, vehicle, now_ns=now_ns, allow_new_lane_change=lane_alignment_may_start(nav, turn_intent),
    )
    intent = lane_intent if lane_intent.signal_requested else (
      turn_intent if settings.turn_signal_enabled else NavLaneIntent(reason="turnSignalsDisabled")
    )
    if not settings.enabled:
      intent = NavLaneIntent(reason="navigationDisabled")

    message = messaging.new_message("navLaneIntentSP")
    message.valid = base_healthy
    state = message.navLaneIntentSP
    state.publishMonoTime = now_ns
    state.valid = base_healthy
    state.signalRequested = intent.signal_requested
    state.laneChangeAuthorized = False
    state.spLaneChangeReady = intent.lane_change_ready
    state.direction = {LaneIntentDirection.none: "none", LaneIntentDirection.left: "left",
                       LaneIntentDirection.right: "right"}[intent.direction]
    state.requestId = intent.request_id
    state.targetLaneIndex = intent.target_lane_index
    lane_request_active = bool(lane_intent.signal_requested and lane_intent.target_lane_index >= 0)
    state.forkNow = bool(lane_request_active and plan.force_fork)
    state.allowUnknownCrossing = bool(lane_request_active and plan.allow_unknown_crossing)
    state.ignoreSolidBoundary = bool(lane_request_active and plan.ignore_solid_boundary)
    state.routeRevision = plan.route_revision
    state.maneuverEventId = plan.maneuver_event_id
    state.reason = intent.reason
    state.sessionId = plan.session_id
    pm.send("navLaneIntentSP", message)
    ratekeeper.keep_time()


if __name__ == "__main__":
  main()
