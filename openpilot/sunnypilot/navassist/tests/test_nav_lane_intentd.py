from dataclasses import replace
from types import SimpleNamespace

from openpilot.sunnypilot.navassist.lane_intent import (
  LaneIntentDirection, LaneTopologyInput, LaneVehicleInput, NavLaneIntentCoordinator,
  NavTurnPlan, NavTurnSignalCoordinator, ObservedLaneChangeState,
)
from openpilot.sunnypilot.navassist.nav_lane_intentd import build_lane_plan, lane_alignment_may_start, navigation_linked
from openpilot.sunnypilot.selfdrive.controls.lib.nav_turn_completion import sp_turn_geometry_active


def nav(**updates):
  values = {
    "stale": False,
    "routeActive": True,
    "routeMatched": True,
    "mode": "realtime",
    "maneuverEventId": 11,
  }
  values.update(updates)
  return SimpleNamespace(**values)


def test_pre_turn_signal_uses_fresh_linked_route_without_full_gps_control_validity():
  assert navigation_linked(nav(), base_healthy=True)


def test_pre_turn_signal_rejects_stale_inactive_unmatched_or_non_realtime_routes():
  assert not navigation_linked(nav(stale=True), base_healthy=True)
  assert not navigation_linked(nav(routeActive=False), base_healthy=True)
  assert not navigation_linked(nav(routeMatched=False), base_healthy=True)
  assert not navigation_linked(nav(mode="simulation"), base_healthy=True)
  assert not navigation_linked(nav(maneuverEventId=0), base_healthy=True)
  assert not navigation_linked(nav(), base_healthy=False)


def test_sp_turn_geometry_uses_existing_vision_lateral_acceleration_threshold():
  straight = SimpleNamespace(desiredCurvature=0.01)
  turning = SimpleNamespace(desiredCurvature=0.015)
  assert not sp_turn_geometry_active(straight, 10.0)
  assert sp_turn_geometry_active(turning, 10.0)


def lane_guidance_nav(**updates):
  values = {
    "valid": True,
    "stale": False,
    "sessionId": "session-a",
    "routeRevision": 3,
    "maneuverEventId": 17,
    "maneuver": "turnLeft",
    "maneuverDistanceM": 800.0,
    "lanes": [],
  }
  values.update(updates)
  return SimpleNamespace(**values)


def topology(count=3):
  return SimpleNamespace(visibleLaneCount=count)


def test_missing_lane_info_uses_visual_extreme_lane_for_ordinary_turns():
  left = build_lane_plan(lane_guidance_nav(maneuver="turnLeft"), topology(), healthy=True)
  right = build_lane_plan(lane_guidance_nav(maneuver="turnRight"), topology(), healthy=True)

  assert left.valid and left.heuristic and left.lane_count == 3 and left.recommended_indices == (0,)
  assert right.valid and right.heuristic and right.lane_count == 3 and right.recommended_indices == (2,)
  assert left.allow_unknown_crossing and right.allow_unknown_crossing
  assert not left.ignore_solid_boundary and not right.ignore_solid_boundary


def test_unanchored_middle_amap_lane_is_not_treated_as_a_visual_absolute_index():
  lanes = [
    SimpleNamespace(index=0, recommended=False),
    SimpleNamespace(index=1, recommended=True),
    SimpleNamespace(index=2, recommended=False),
  ]
  plan = build_lane_plan(lane_guidance_nav(maneuver="turnLeft", lanes=lanes), topology(), healthy=True)

  assert not plan.valid
  assert not plan.heuristic
  assert plan.recommended_indices == ()


def test_amap_edge_recommendation_qualifies_relative_extreme_on_wider_road():
  lanes = [SimpleNamespace(index=index, recommended=index == 0) for index in range(4)]

  plan = build_lane_plan(lane_guidance_nav(maneuver="turnLeft", lanes=lanes), topology(count=3), healthy=True)

  assert plan.valid and plan.heuristic
  assert plan.lane_count == 3
  assert plan.recommended_indices == (0,)


def test_turn_fallback_is_bounded_while_exit_fallback_starts_farther_out():
  far_turn = build_lane_plan(
    lane_guidance_nav(maneuver="turnLeft", maneuverDistanceM=1_500.0), topology(), healthy=True,
  )
  far_exit = build_lane_plan(
    lane_guidance_nav(maneuver="exitRight", maneuverDistanceM=1_500.0), topology(), healthy=True,
  )

  assert not far_turn.heuristic and far_turn.recommended_indices == ()
  assert far_exit.heuristic and far_exit.recommended_indices == (2,)


def test_imminent_exit_builds_a_bounded_cp_style_fork_now_policy():
  plan = build_lane_plan(
    lane_guidance_nav(maneuver="exitRight", maneuverDistanceM=50.0), topology(count=1), healthy=True,
  )

  assert plan.valid and plan.heuristic
  assert plan.edge_direction == LaneIntentDirection.right
  assert plan.force_fork
  assert plan.allow_unknown_crossing
  assert plan.ignore_solid_boundary


def test_slight_turn_without_lane_info_does_not_force_an_extreme_lane():
  plan = build_lane_plan(lane_guidance_nav(maneuver="slightLeft"), topology(), healthy=True)

  assert not plan.heuristic
  assert plan.recommended_indices == ()


def test_started_relative_change_keeps_identity_through_local_lane_count_change_and_observation_gap():
  coordinator = NavLaneIntentCoordinator()
  guidance = lane_guidance_nav(maneuver="turnRight")
  current_plan = build_lane_plan(guidance, topology(count=3), healthy=True)
  observed = LaneTopologyInput(True, 3, 1, True, True, True, True)
  car = LaneVehicleInput(True, 15.0)
  for now_ns in (0, 500_000_000, 1_000_000_000):
    coordinator.update(current_plan, observed, car, now_ns=now_ns)
  changing_car = replace(car, right_blinker=True, lane_change_state=ObservedLaneChangeState.starting,
                         lane_change_direction=LaneIntentDirection.right)
  assert coordinator.update(current_plan, observed, changing_car, now_ns=1_200_000_000).signal_requested

  # The route and physical lateral state remain valid while visible lanes
  # recenter and then disappear briefly from the observation.
  recentered_plan = build_lane_plan(guidance, topology(count=2), healthy=True)
  recentered = coordinator.update(recentered_plan, replace(observed, visible_lane_count=2), changing_car,
                                 now_ns=1_300_000_000)
  assert recentered.signal_requested and recentered.reason == "heuristicChanging"
  missing_plan = build_lane_plan(guidance, topology(count=0), healthy=True)
  assert missing_plan.valid
  unavailable = replace(observed, valid_for_control=False, visible_lane_count=0, ego_lane_index=-1)
  gap = coordinator.update(missing_plan, unavailable, changing_car, now_ns=1_400_000_000)
  assert gap.signal_requested and gap.reason == "heuristicTopologyTransition"
  expired = coordinator.update(missing_plan, unavailable, changing_car, now_ns=2_400_000_001)
  assert not expired.signal_requested and expired.reason == "topologyTransitionTimeout"


def test_existing_turn_window_hands_off_after_started_sp_cycle_without_another_lane_change():
  coordinator = NavLaneIntentCoordinator()
  turn_coordinator = NavTurnSignalCoordinator()
  guidance = lane_guidance_nav(maneuver="turnLeft", maneuverDistanceM=500.0)
  current_plan = build_lane_plan(guidance, topology(), healthy=True)
  observed = LaneTopologyInput(True, 3, 1, True, True, True, True)
  car = LaneVehicleInput(True, 15.0)
  for now_ns in (0, 500_000_000, 1_000_000_000):
    coordinator.update(current_plan, observed, car, now_ns=now_ns)

  # At 15 m/s the existing pre-turn window is 140 m. Reaching it while
  # SP reports starting must retain the same lane-change lamp and desire.
  guidance.maneuverDistanceM = 140.0
  turn = turn_coordinator.update(NavTurnPlan(True, "session-a", 3, 17, "turnLeft", 140.0),
                                 speed_mps=15.0, now_ns=1_200_000_000)
  assert turn.signal_requested and turn.target_lane_index == -1
  changing_car = replace(car, left_blinker=True, lane_change_state=ObservedLaneChangeState.starting,
                         lane_change_direction=LaneIntentDirection.left)
  started = coordinator.update(build_lane_plan(guidance, topology(), healthy=True), observed, changing_car,
                               now_ns=1_200_000_000, allow_new_lane_change=lane_alignment_may_start(guidance, turn))
  assert started.signal_requested and started.target_lane_index >= 0

  # Deceleration below the start threshold must not cut an SP action already
  # underway. The real SP state cycle ends at pre, then gets stable confirmation.
  finishing_car = replace(changing_car, speed_mps=8.0, lane_change_state=ObservedLaneChangeState.finishing)
  for now_ns in (1_500_000_000, 2_000_000_000):
    assert coordinator.update(current_plan, observed, finishing_car, now_ns=now_ns,
                              allow_new_lane_change=False).signal_requested
  completed_car = replace(finishing_car, lane_change_state=ObservedLaneChangeState.pre)
  assert coordinator.update(current_plan, observed, completed_car, now_ns=2_100_000_000,
                            allow_new_lane_change=False).signal_requested
  completed = coordinator.update(current_plan, observed, completed_car, now_ns=2_600_000_000,
                                 allow_new_lane_change=False)
  assert not completed.signal_requested and completed.reason == "laneChangeObserved"
  selected = completed if completed.signal_requested else turn
  assert selected.target_lane_index == -1 and selected.signal_requested

  next_request = coordinator.update(current_plan, observed, car, now_ns=6_000_000_000,
                                    allow_new_lane_change=False)
  assert not next_request.signal_requested


def test_turn_window_releases_pending_lane_signal_before_sp_starts():
  coordinator = NavLaneIntentCoordinator()
  current_plan = build_lane_plan(lane_guidance_nav(), topology(), healthy=True)
  observed = LaneTopologyInput(True, 3, 1, True, True, True, True)
  car = LaneVehicleInput(True, 15.0)
  for now_ns in (0, 500_000_000):
    coordinator.update(current_plan, observed, car, now_ns=now_ns)
  assert coordinator.update(current_plan, observed, car, now_ns=1_000_000_000).signal_requested
  approaching = coordinator.update(current_plan, observed, car, now_ns=1_200_000_000,
                                   allow_new_lane_change=False)
  assert not approaching.signal_requested and approaching.reason == "turnApproachHandoff"


def test_zero_distance_allows_existing_plan_to_finish_but_never_starts_a_new_change():
  for maneuver in ("turnLeft", "exitRight"):
    guidance = lane_guidance_nav(maneuver=maneuver, maneuverDistanceM=0.0)
    turn = NavTurnSignalCoordinator().update(NavTurnPlan(True, "session-a", 3, 17, maneuver, 0.0),
                                            speed_mps=15.0, now_ns=0)
    assert not turn.signal_requested
    assert build_lane_plan(guidance, topology(), healthy=True).valid
    assert not lane_alignment_may_start(guidance, turn)


def test_lane_change_hard_timeout_still_applies_during_observation_grace():
  coordinator = NavLaneIntentCoordinator()
  current_plan = build_lane_plan(lane_guidance_nav(), topology(), healthy=True)
  observed = LaneTopologyInput(True, 3, 1, True, True, True, True)
  car = LaneVehicleInput(True, 15.0)
  for now_ns in (0, 500_000_000, 1_000_000_000):
    coordinator.update(current_plan, observed, car, now_ns=now_ns)
  changing_car = replace(car, left_blinker=True, lane_change_state=ObservedLaneChangeState.starting,
                         lane_change_direction=LaneIntentDirection.left)
  coordinator.update(current_plan, observed, changing_car, now_ns=1_200_000_000)
  missing = replace(observed, valid_for_control=False)
  grace = coordinator.update(current_plan, missing, changing_car, now_ns=11_000_000_000)
  assert grace.signal_requested
  expired = coordinator.update(current_plan, missing, changing_car, now_ns=11_200_000_001)
  assert not expired.signal_requested and expired.reason == "laneChangeTimeout"
