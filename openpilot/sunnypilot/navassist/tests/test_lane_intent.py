from openpilot.sunnypilot.navassist.lane_intent import (
  LaneIntentDirection,
  LaneTopologyInput,
  LaneVehicleInput,
  NavLaneIntentCoordinator,
  NavLanePlan,
  NavTurnPlan,
  NavTurnSignalCoordinator,
  ObservedLaneChangeState,
)


def plan(*, recommended=(0,), lane_count=3, valid=True, session="session-a", revision=1, event=1):
  return NavLanePlan(valid, session, revision, event, lane_count, tuple(recommended))


def topology(*, ego=1, count=3, left=True, right=True, left_cross=False, right_cross=False, valid=True):
  return LaneTopologyInput(valid, count, ego, left, right, left_cross, right_cross)


def vehicle(*, bsm_left=False, bsm_right=False, state=ObservedLaneChangeState.off,
            direction=LaneIntentDirection.none, lat=True, left_blinker=False, right_blinker=False):
  return LaneVehicleInput(lat, 15.0, bsm_left, bsm_right, left_blinker, right_blinker, lane_change_state=state,
                          lane_change_direction=direction)


def turn_plan(*, valid=True, maneuver="turnLeft", distance=100.0, session="session-a", revision=1, event=11):
  return NavTurnPlan(valid, session, revision, event, maneuver, distance)


def test_navigation_turn_signal_starts_before_turn_without_a_lane_target():
  coordinator = NavTurnSignalCoordinator()

  intent = coordinator.update(turn_plan(), speed_mps=15.0, now_ns=0)

  assert intent.signal_requested
  assert not intent.lane_change_ready
  assert intent.direction == LaneIntentDirection.left
  assert intent.target_lane_index == -1
  assert intent.request_id == 11
  assert intent.reason == "turnApproach"


def test_heuristic_extreme_lane_waits_for_stable_neighbor_then_signals_one_lane_at_a_time():
  coordinator = NavLaneIntentCoordinator()
  heuristic = NavLanePlan(True, "session-a", 1, 7, 3, (0,), heuristic=True)

  first = coordinator.update(heuristic, topology(ego=2), vehicle(), now_ns=0)
  stable_neighbor = coordinator.update(heuristic, topology(ego=2), vehicle(), now_ns=500_000_000)
  intent = coordinator.update(heuristic, topology(ego=2, left_cross=True), vehicle(), now_ns=1_000_000_000)

  assert not first.signal_requested and first.reason == "heuristicStabilizingNeighbor"
  assert not stable_neighbor.signal_requested and stable_neighbor.reason == "heuristicStabilizingLaneAlignment"
  assert intent.signal_requested and not intent.lane_change_ready
  assert intent.direction == LaneIntentDirection.left
  assert intent.target_lane_index == 1
  assert intent.reason == "heuristicSignaling"


def test_fork_now_can_signal_without_a_visible_neighbor_but_keeps_lane_change_state_machine():
  coordinator = NavLaneIntentCoordinator()
  forced = NavLanePlan(
    True, "session-a", 1, 7, 1, (0,), heuristic=True,
    edge_direction=LaneIntentDirection.right, force_fork=True,
    allow_unknown_crossing=True, ignore_solid_boundary=True,
  )

  intent = coordinator.update(
    forced, topology(ego=0, count=1, left=False, right=False, right_cross=True), vehicle(), now_ns=0,
  )

  assert intent.signal_requested
  assert intent.direction == LaneIntentDirection.right
  assert intent.target_lane_index == 1
  assert not intent.lane_change_ready


def test_navigation_turn_signal_supports_right_turns_and_waits_until_lookahead_window():
  coordinator = NavTurnSignalCoordinator()

  early = coordinator.update(turn_plan(maneuver="turnRight", distance=200.0), speed_mps=15.0, now_ns=0)
  active = coordinator.update(turn_plan(maneuver="turnRight", distance=130.0), speed_mps=15.0, now_ns=1_000_000_000)

  assert not early.signal_requested
  assert active.signal_requested
  assert active.direction == LaneIntentDirection.right


def test_navigation_merge_requests_directional_lamp_without_authorizing_lane_change():
  coordinator = NavTurnSignalCoordinator()

  intent = coordinator.update(turn_plan(maneuver="mergeRight", distance=80.0), speed_mps=10.0, now_ns=0)

  assert intent.signal_requested
  assert intent.direction == LaneIntentDirection.right
  assert not intent.lane_change_ready
  assert intent.target_lane_index == -1


def test_navigation_turn_signal_stays_on_through_zero_distance_then_cancels_on_event_change():
  coordinator = NavTurnSignalCoordinator()
  coordinator.update(turn_plan(distance=50.0), speed_mps=10.0, now_ns=0)

  at_turn = coordinator.update(turn_plan(distance=0.0), speed_mps=8.0, now_ns=5_000_000_000)
  changed = coordinator.update(turn_plan(maneuver="straight", distance=300.0, event=12), speed_mps=8.0,
                               now_ns=6_000_000_000)

  assert at_turn.signal_requested
  assert not changed.signal_requested


def test_navigation_turn_signal_waits_for_sp_turn_geometry_to_clear_after_event_change():
  coordinator = NavTurnSignalCoordinator()
  coordinator.update(turn_plan(distance=80.0), speed_mps=12.0, now_ns=0)

  changed_while_turning = coordinator.update(
    turn_plan(maneuver="straight", distance=500.0, event=12), speed_mps=6.0,
    now_ns=5_000_000_000, turn_geometry_active=True,
  )
  first_clear = coordinator.update(
    turn_plan(maneuver="straight", distance=490.0, event=12), speed_mps=6.0,
    now_ns=6_000_000_000, turn_geometry_active=False,
  )
  completed = coordinator.update(
    turn_plan(maneuver="straight", distance=480.0, event=12), speed_mps=6.0,
    now_ns=6_500_000_001, turn_geometry_active=False,
  )

  assert changed_while_turning.signal_requested and changed_while_turning.reason == "turnCompletion"
  assert first_clear.signal_requested and first_clear.reason == "turnCompletion"
  assert not completed.signal_requested


def test_navigation_turn_signal_does_not_survive_a_route_revision_change():
  coordinator = NavTurnSignalCoordinator()
  coordinator.update(turn_plan(), speed_mps=10.0, now_ns=0)

  changed = coordinator.update(
    turn_plan(revision=2, event=12), speed_mps=6.0, now_ns=1_000_000_000,
    turn_geometry_active=True,
  )

  assert not changed.signal_requested and changed.reason == "turnChanged"


def test_navigation_turn_signal_holds_through_recorded_snapshot_gaps_until_maneuver_changes():
  coordinator = NavTurnSignalCoordinator()
  started = coordinator.update(turn_plan(maneuver="turnRight", distance=120.0), speed_mps=13.5, now_ns=0)
  first_gap = coordinator.update(
    turn_plan(valid=False, maneuver="turnRight", distance=11.0), speed_mps=2.0, now_ns=17_946_000_000,
  )
  recovered = coordinator.update(
    turn_plan(maneuver="turnRight", distance=10.0), speed_mps=2.0, now_ns=18_046_000_000,
  )
  second_gap = coordinator.update(
    turn_plan(valid=False, maneuver="turnRight", distance=8.0), speed_mps=2.0, now_ns=19_747_000_000,
  )
  at_turn = coordinator.update(
    turn_plan(maneuver="turnRight", distance=0.0), speed_mps=1.0, now_ns=24_046_000_000,
  )
  completed = coordinator.update(
    turn_plan(maneuver="straight", distance=4_964.0, event=12), speed_mps=6.0, now_ns=29_446_000_000,
  )

  assert started.signal_requested
  assert first_gap.signal_requested and first_gap.reason == "turnApproachGrace"
  assert recovered.signal_requested
  assert second_gap.signal_requested and second_gap.reason == "turnApproachGrace"
  assert at_turn.signal_requested
  assert not completed.signal_requested


def test_navigation_turn_signal_retains_a_bounded_hard_timeout():
  coordinator = NavTurnSignalCoordinator()
  coordinator.update(turn_plan(), speed_mps=15.0, now_ns=0)

  timed_out = coordinator.update(
    turn_plan(), speed_mps=15.0, now_ns=NavTurnSignalCoordinator.SIGNAL_TIMEOUT_NS + 1,
  )
  assert not timed_out.signal_requested


def test_navigation_turn_signal_drops_after_the_bounded_plan_gap_grace():
  coordinator = NavTurnSignalCoordinator()
  coordinator.update(turn_plan(), speed_mps=15.0, now_ns=0)
  first_gap = coordinator.update(turn_plan(valid=False), speed_mps=15.0, now_ns=1_000_000_000)
  expired = coordinator.update(
    turn_plan(valid=False), speed_mps=15.0,
    now_ns=1_000_000_000 + NavTurnSignalCoordinator.PLAN_GAP_GRACE_NS + 1,
  )

  assert first_gap.signal_requested
  assert not expired.signal_requested and expired.reason == "turnUnavailable"


def test_signal_waits_at_solid_line_then_authorizes_after_dashed_is_stable():
  coordinator = NavLaneIntentCoordinator()
  first_mismatch = coordinator.update(plan(), topology(), vehicle(), now_ns=0)
  assert not first_mismatch.signal_requested and not first_mismatch.lane_change_ready
  assert first_mismatch.reason == "stabilizingLaneAlignment"
  waiting = coordinator.update(plan(), topology(), vehicle(), now_ns=500_000_000)
  assert not waiting.signal_requested and waiting.reason == "waitingCrossing"
  first_dashed = coordinator.update(plan(), topology(left_cross=True), vehicle(left_blinker=True), now_ns=600_000_000)
  assert first_dashed.signal_requested and not first_dashed.lane_change_ready
  authorized = coordinator.update(plan(), topology(left_cross=True), vehicle(left_blinker=True), now_ns=900_000_000)
  assert authorized.signal_requested and authorized.lane_change_ready
  assert authorized.direction == LaneIntentDirection.left


def test_blindspot_delays_physical_signal_until_the_lane_change_can_start():
  coordinator = NavLaneIntentCoordinator()
  coordinator.update(plan(recommended=(2,)), topology(right_cross=True), vehicle(), now_ns=0)
  coordinator.update(plan(recommended=(2,)), topology(right_cross=True),
                     vehicle(bsm_right=True, right_blinker=True), now_ns=500_000_000)
  blocked = coordinator.update(plan(recommended=(2,)), topology(right_cross=True),
                               vehicle(bsm_right=True, right_blinker=True), now_ns=900_000_000)
  assert not blocked.signal_requested and blocked.reason == "waitingBlindspot"

  signaling = coordinator.update(
    plan(recommended=(2,)), topology(right_cross=True), vehicle(right_blinker=True), now_ns=1_000_000_000,
  )
  assert signaling.signal_requested and not signaling.lane_change_ready


def test_software_signal_request_never_authorizes_without_physical_blinker_feedback():
  coordinator = NavLaneIntentCoordinator()
  coordinator.update(plan(), topology(left_cross=True), vehicle(), now_ns=0)
  coordinator.update(plan(), topology(left_cross=True), vehicle(), now_ns=500_000_000)
  waiting = coordinator.update(plan(), topology(left_cross=True), vehicle(), now_ns=1_000_000_000)
  assert waiting.signal_requested and not waiting.lane_change_ready


def test_lane_count_mismatch_unknown_topology_and_no_neighbor_fail_closed():
  for observed in (
    topology(count=2),
    topology(valid=False),
    topology(left=False),
  ):
    coordinator = NavLaneIntentCoordinator()
    coordinator.update(plan(), observed, vehicle(), now_ns=0)
    assert not coordinator.update(plan(), observed, vehicle(), now_ns=1_000_000_000).signal_requested


def test_one_lane_change_completes_before_another_request_is_considered():
  coordinator = NavLaneIntentCoordinator()
  coordinator.update(plan(recommended=(0,)), topology(ego=2, left_cross=True), vehicle(), now_ns=0)
  coordinator.update(plan(recommended=(0,)), topology(ego=2, left_cross=True), vehicle(), now_ns=500_000_000)
  coordinator.update(plan(recommended=(0,)), topology(ego=2, left_cross=True), vehicle(left_blinker=True), now_ns=800_000_000)
  changing = coordinator.update(
    plan(recommended=(0,)), topology(ego=2, left_cross=True),
    vehicle(state=ObservedLaneChangeState.starting, direction=LaneIntentDirection.left, left_blinker=True), now_ns=900_000_000,
  )
  assert changing.signal_requested and changing.target_lane_index == 1
  observed = coordinator.update(
    plan(recommended=(0,)), topology(ego=1, left_cross=True),
    vehicle(state=ObservedLaneChangeState.pre, direction=LaneIntentDirection.left, left_blinker=True), now_ns=1_000_000_000,
  )
  assert observed.signal_requested
  finishing = coordinator.update(
    plan(recommended=(0,)), topology(ego=1, left_cross=True),
    vehicle(state=ObservedLaneChangeState.pre, direction=LaneIntentDirection.left, left_blinker=True), now_ns=1_500_000_000,
  )
  assert not finishing.signal_requested and finishing.reason == "laneChangeObserved"
  complete = coordinator.update(plan(recommended=(0,)), topology(ego=1, left_cross=True), vehicle(),
                                now_ns=2_300_000_000)
  assert not complete.signal_requested and complete.reason == "laneChangeComplete"


def test_relative_extreme_lane_change_uses_sp_cycle_when_visual_index_recenters():
  coordinator = NavLaneIntentCoordinator()
  heuristic = NavLanePlan(True, "session-a", 1, 7, 3, (0,), heuristic=True)
  coordinator.update(heuristic, topology(ego=1, left_cross=True), vehicle(), now_ns=0)
  coordinator.update(heuristic, topology(ego=1, left_cross=True), vehicle(), now_ns=500_000_000)
  coordinator.update(heuristic, topology(ego=1, left_cross=True), vehicle(left_blinker=True), now_ns=1_000_000_000)
  coordinator.update(heuristic, topology(ego=1, left_cross=True), vehicle(left_blinker=True), now_ns=1_300_000_000)
  coordinator.update(
    heuristic, topology(ego=1, left_cross=True),
    vehicle(state=ObservedLaneChangeState.starting, direction=LaneIntentDirection.left, left_blinker=True),
    now_ns=1_400_000_000,
  )

  completing = coordinator.update(
    heuristic, topology(ego=1, left_cross=True),
    vehicle(state=ObservedLaneChangeState.pre, direction=LaneIntentDirection.left, left_blinker=True),
    now_ns=1_500_000_000,
  )
  completed = coordinator.update(
    heuristic, topology(ego=1, left_cross=True),
    vehicle(state=ObservedLaneChangeState.pre, direction=LaneIntentDirection.left, left_blinker=True),
    now_ns=2_000_000_000,
  )

  assert completing.signal_requested
  assert not completed.signal_requested and completed.reason == "laneChangeObserved"


def test_wrong_observed_lane_change_direction_aborts_and_latches_event():
  coordinator = NavLaneIntentCoordinator()
  coordinator.update(plan(), topology(left_cross=True), vehicle(), now_ns=0)
  coordinator.update(plan(), topology(left_cross=True), vehicle(left_blinker=True), now_ns=500_000_000)
  aborted = coordinator.update(
    plan(), topology(left_cross=True),
    vehicle(state=ObservedLaneChangeState.starting, direction=LaneIntentDirection.right, left_blinker=True), now_ns=900_000_000,
  )
  assert not aborted.signal_requested and aborted.reason == "directionMismatch"
  assert coordinator.update(plan(), topology(left_cross=True), vehicle(), now_ns=2_000_000_000).reason == "blockedEvent"


def test_new_navigation_session_never_inherits_old_block_or_active_intent():
  coordinator = NavLaneIntentCoordinator()
  coordinator.update(plan(session="old"), topology(left_cross=True), vehicle(), now_ns=0)
  coordinator.update(plan(session="old"), topology(left_cross=True), vehicle(left_blinker=True), now_ns=500_000_000)
  coordinator.update(
    plan(session="old"), topology(left_cross=True),
    vehicle(state=ObservedLaneChangeState.starting, direction=LaneIntentDirection.right, left_blinker=True),
    now_ns=900_000_000,
  )
  assert coordinator.update(plan(session="old"), topology(left_cross=True), vehicle(),
                            now_ns=1_000_000_000).reason == "blockedEvent"
  fresh = coordinator.update(plan(session="new"), topology(left_cross=True), vehicle(), now_ns=1_100_000_000)
  assert fresh.reason == "stabilizingLaneAlignment"


def test_expected_source_pair_transition_during_lane_change_has_bounded_grace():
  coordinator = NavLaneIntentCoordinator()
  coordinator.update(plan(recommended=(0,)), topology(ego=2, left_cross=True), vehicle(), now_ns=0)
  coordinator.update(plan(recommended=(0,)), topology(ego=2, left_cross=True),
                     vehicle(left_blinker=True), now_ns=500_000_000)
  coordinator.update(plan(recommended=(0,)), topology(ego=2, left_cross=True),
                     vehicle(left_blinker=True), now_ns=800_000_000)
  coordinator.update(
    plan(recommended=(0,)), topology(ego=2, left_cross=True),
    vehicle(state=ObservedLaneChangeState.starting, direction=LaneIntentDirection.left, left_blinker=True),
    now_ns=900_000_000,
  )
  transition = coordinator.update(
    plan(recommended=(0,)), topology(ego=-1, valid=False),
    vehicle(state=ObservedLaneChangeState.starting, direction=LaneIntentDirection.left, left_blinker=True),
    now_ns=1_000_000_000,
  )
  assert transition.signal_requested and transition.reason == "topologyTransition"
  coordinator.update(
    plan(recommended=(0,)), topology(ego=1, left_cross=True),
    vehicle(state=ObservedLaneChangeState.pre, direction=LaneIntentDirection.left, left_blinker=True),
    now_ns=1_200_000_000,
  )
  observed = coordinator.update(
    plan(recommended=(0,)), topology(ego=1, left_cross=True),
    vehicle(state=ObservedLaneChangeState.pre, direction=LaneIntentDirection.left, left_blinker=True),
    now_ns=1_700_000_000,
  )
  assert not observed.signal_requested and observed.reason == "laneChangeObserved"


def test_long_solid_wait_gets_a_fresh_lane_change_timeout_when_dashed_appears():
  coordinator = NavLaneIntentCoordinator()
  coordinator.update(plan(), topology(), vehicle(), now_ns=0)
  coordinator.update(plan(), topology(), vehicle(), now_ns=500_000_000)
  coordinator.update(plan(), topology(left_cross=True), vehicle(left_blinker=True), now_ns=11_000_000_000)
  authorized = coordinator.update(plan(), topology(left_cross=True), vehicle(left_blinker=True), now_ns=11_300_000_000)
  assert authorized.lane_change_ready
  still_authorized = coordinator.update(plan(), topology(left_cross=True), vehicle(left_blinker=True), now_ns=11_350_000_000)
  assert still_authorized.lane_change_ready
