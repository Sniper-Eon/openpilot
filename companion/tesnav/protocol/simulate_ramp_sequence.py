"""Offline time-series simulation; synthetic sensors/model probability, no vehicle I/O."""
import json
from copy import deepcopy
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from openpilot.cereal import log
from openpilot.sunnypilot.navassist.protocol import AcceptedSnapshot, parse_snapshot
from openpilot.sunnypilot.navassist.publisher import build_nav_assist_message
from openpilot.sunnypilot.navassist.nav_lane_intentd import (
  build_lane_plan, apply_oem_signal_gate, oem_gate_reason, apply_radar_target_gate, lane_alignment_may_start,
)
from openpilot.sunnypilot.navassist.lane_intent import (
  LaneIntentDirection, LaneTopologyInput, LaneVehicleInput, NavLaneIntentCoordinator,
  ObservedLaneChangeState, NavTurnPlan, NavTurnSignalCoordinator,
)
from openpilot.sunnypilot.selfdrive.controls.lib.tests.test_nav_lane_intent_desire import helper, car_state


def nav_from(packet, now):
  parsed = parse_snapshot(json.dumps(packet).encode())
  return build_nav_assist_message(AcceptedSnapshot(parsed, now, now + 1_200_000_000), now).navAssistStateSP


def simulate(packets, kind, side, scenario):
  coordinator, dh, turn_coordinator = NavLaneIntentCoordinator(), helper(), NavTurnSignalCoordinator()
  model = NS(laneLines=[NS(x=[0., 100.], y=[y, y]) for y in (-5.25, -1.75, 1.75, 5.25)])
  topology = LaneTopologyInput(True, 3, 1, True, True, True, True)
  far = nav_from(packets[f'{kind}-{side}-1500'], 1_000_000_000)
  # Explicitly simulate the road-class transition to elevated expressway.
  near_packet = deepcopy(packets[f'{kind}-{side}-50'])
  near_packet['guidance']['roadClass'] = 6
  near = nav_from(near_packet, 1_000_000_000)
  jitter = []
  for distance in (90, 0):
    packet = deepcopy(near_packet)
    packet['guidance']['maneuverDistanceM'] = distance
    jitter.append(nav_from(packet, 1_000_000_000))
  lamp = False
  approach_completed = fork_completed = False
  starts = 0
  trace, previous = [], None
  block_frames = lost_frames = 0
  for frame in range(600):
    now = 1_000_000_000 + frame * 50_000_000
    near_phase = frame >= 240
    nav = near if near_phase else far
    speed = 5. if near_phase else 23.5
    old_state = dh.lane_change_state
    if scenario == 'distance_jitter' and near_phase and old_state == log.LaneChangeState.laneChangeStarting:
      nav = jitter[frame % 2]
    # Environment changes are explicitly synthetic, never inferred from real footage.
    observed = topology
    if scenario == 'vision_loss' and near_phase and old_state in (log.LaneChangeState.laneChangeStarting, log.LaneChangeState.laneChangeFinishing):
      observed = replace(topology, valid_for_control=False, left_neighbor_exists=None, right_neighbor_exists=None)
      lost_frames += 1
    plan = build_lane_plan(nav, NS(visibleLaneCount=3), healthy=True)
    car = car_state(vEgo=speed, **{side + 'Blinker': lamp})
    vehicle = LaneVehicleInput(True, speed, left_blinker=car.leftBlinker, right_blinker=car.rightBlinker,
      lane_change_state=ObservedLaneChangeState(int(old_state)),
      lane_change_direction=LaneIntentDirection(int(dh.lane_change_direction)))
    turn = turn_coordinator.update(NavTurnPlan(True, str(nav.sessionId), int(nav.routeRevision),
      int(nav.maneuverEventId), str(nav.maneuver), float(nav.maneuverDistanceM)), speed_mps=speed, now_ns=now)
    request = coordinator.update(plan, observed, vehicle, now_ns=now,
      allow_new_lane_change=lane_alignment_may_start(nav, turn, speed_mps=speed))
    request = apply_oem_signal_gate(request, oem_gate_reason(plan, observed, {}), coordinator._phase)
    blocked = (scenario == 'target_then_clear' and (frame < 40 or 240 <= frame < 280)) or (scenario == 'target_stays' and near_phase)
    target = NS(dRel=4., yRel=3.4 if side == 'left' else -3.4, vRel=-3., deprecated=NS(measured=True))
    request = apply_radar_target_gate(request, NS(points=[target] if blocked else []), model,
                                      speed_mps=speed, healthy=True)
    if blocked and request.signal_requested:
      block_frames += 1
      assert not request.lane_change_ready, (kind, side, scenario, frame, request)
    actual_side = {LaneIntentDirection.none: 'none', LaneIntentDirection.left: 'left', LaneIntentDirection.right: 'right'}[request.direction]
    if request.signal_requested:
      assert actual_side == side, (kind, side, scenario, frame, request)
    wire = NS(valid=True, signalRequested=request.signal_requested, targetLaneIndex=request.target_lane_index,
      direction=actual_side, spLaneChangeReady=request.lane_change_ready, forkNow=coordinator.fork_active,
      sessionId=plan.session_id, maneuverEventId=plan.maneuver_event_id, requestId=request.request_id)
    # A synthetic probability decrease exercises normal native completion; it is not a model inference replay.
    probability = 0. if old_state in (log.LaneChangeState.laneChangeStarting, log.LaneChangeState.laneChangeFinishing) else 1.
    if scenario == 'model_never_completes' and near_phase:
      probability = 1.
    dh.update(car, True, probability, nav_lane_intent=wire, left_crossing_allowed=True, right_crossing_allowed=True)
    new_start = dh.lane_change_state == log.LaneChangeState.laneChangeStarting and old_state != dh.lane_change_state
    if new_start:
      assert not blocked
      starts += 1
    if request.reason == 'laneChangeObserved':
      approach_completed = True
      topology = replace(topology, ego_lane_index=0 if side == 'left' else 2,
                         left_neighbor_exists=side != 'left', right_neighbor_exists=side != 'right')
    if request.reason == 'forkCompleted':
      fork_completed = True
    item = (near_phase, request.reason, request.signal_requested, request.lane_change_ready,
            int(dh.lane_change_state), int(dh.desire), wire.forkNow)
    if item != previous:
      trace.append(dict(t=frame * .05, near=near_phase, reason=request.reason, signal=request.signal_requested,
                        ready=request.lane_change_ready, state=int(dh.lane_change_state), desire=int(dh.desire), fork=wire.forkNow))
      previous = item
    lamp = request.signal_requested and not (scenario == 'no_lamp_feedback' and near_phase)
  should_complete = scenario not in ('target_stays', 'no_lamp_feedback', 'model_never_completes')
  expected_starts = 1 if scenario in ('target_stays', 'no_lamp_feedback') else 2
  assert approach_completed and fork_completed == should_complete and starts == expected_starts, (kind, side, scenario, starts, trace)
  if scenario == 'target_then_clear': assert block_frames > 0
  if scenario == 'vision_loss': assert lost_frames > 0
  return dict(roadType=kind, side=side, scenario=scenario, starts=starts, approachCompleted=approach_completed,
              forkCompleted=fork_completed, radarBlockedFrames=block_frames, visionLostFrames=lost_frames, trace=trace)


if __name__ == '__main__':
  packets = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
  results = [simulate(packets, kind, side, scenario)
             for kind in ('6', '8', '9', '10') for side in ('left', 'right')
             for scenario in ('clear', 'target_then_clear', 'vision_loss', 'distance_jitter', 'target_stays', 'no_lamp_feedback', 'model_never_completes')]
  print('SIMULATION_JSON=' + json.dumps(results))
  print(f'PASS: {len(results)} continuous App approach -> fork sequences; completion and non-completion assertions passed')
