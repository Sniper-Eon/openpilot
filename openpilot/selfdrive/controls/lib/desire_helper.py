from openpilot.cereal import log, custom
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.sunnypilot.selfdrive.controls.lib.auto_lane_change import AutoLaneChangeController, AutoLaneChangeMode
from openpilot.sunnypilot.selfdrive.controls.lib.lane_turn_desire import LaneTurnController

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection
TurnDirection = custom.ModelDataV2SP.TurnDirection

LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.
LANE_CHANGE_START_TIME = 0.5

TURN_DESIRES = {
  TurnDirection.none: log.Desire.none,
  TurnDirection.turnLeft: log.Desire.turnLeft,
  TurnDirection.turnRight: log.Desire.turnRight,
}

class DesireHelper:
  def __init__(self):
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.prev_one_blinker = False
    self.desire = log.Desire.none
    self.alc = AutoLaneChangeController(self)
    self.lane_turn_controller = LaneTurnController(self)
    self.lane_turn_direction = TurnDirection.none
    self._active_nav_signal_direction: str | None = None
    self._active_nav_signal_turn_only = False
    self._active_nav_signal_feedback = False
    self._nav_signal_tail_direction: str | None = None
    self._nav_signal_tail_turn_only = False

  @staticmethod
  def get_lane_change_direction(left_blinker, right_blinker):
    return LaneChangeDirection.left if left_blinker and not right_blinker else LaneChangeDirection.right

  def update(self, carstate, lateral_active, lane_change_prob, left_edge_detected=False, right_edge_detected=False,
             nav_lane_intent=None, left_line_blocked=False, right_line_blocked=False,
             left_crossing_allowed=False, right_crossing_allowed=False):
    self.alc.update_params()
    self.lane_turn_controller.update_params()
    v_ego = carstate.vEgo
    # targetLaneIndex < 0 is a physical pre-turn lamp request only. Keep it out
    # of the lane-change state machine so an upcoming turn cannot become a
    # lateral lane-change desire.
    nav_requested = bool(
      nav_lane_intent is not None and nav_lane_intent.valid and nav_lane_intent.signalRequested
    )
    nav_direction = str(nav_lane_intent.direction) if nav_requested else "none"
    nav_signal = bool(nav_requested and nav_lane_intent.targetLaneIndex >= 0)
    nav_turn_only = bool(nav_requested and nav_lane_intent.targetLaneIndex < 0 and nav_direction in ("left", "right"))
    if (self._active_nav_signal_direction is not None
        and (not nav_requested or nav_direction != self._active_nav_signal_direction)):
      if self._active_nav_signal_feedback:
        self._nav_signal_tail_direction = self._active_nav_signal_direction
        self._nav_signal_tail_turn_only = self._active_nav_signal_turn_only
      self._active_nav_signal_direction = None
      self._active_nav_signal_turn_only = False
      self._active_nav_signal_feedback = False
    if nav_requested and nav_direction in ("left", "right"):
      if nav_direction != self._active_nav_signal_direction:
        self._active_nav_signal_feedback = False
      self._active_nav_signal_direction = nav_direction
      self._active_nav_signal_turn_only = nav_turn_only
      # A new request owns a same-direction lamp even if the previous request's
      # cancellation has not turned it off. Its current purpose replaces the
      # old tail; turn-only requests still suppress the ALC entrance below.
      if self._nav_signal_tail_direction == nav_direction:
        self._nav_signal_tail_direction = None
        self._nav_signal_tail_turn_only = False
      physical_nav_signal_on = ((nav_direction == "left" and carstate.leftBlinker and not carstate.rightBlinker)
                                or (nav_direction == "right" and carstate.rightBlinker and not carstate.leftBlinker))
      self._active_nav_signal_feedback |= physical_nav_signal_on
    if self._nav_signal_tail_direction is not None:
      tail_signal_on = ((self._nav_signal_tail_direction == "left" and carstate.leftBlinker and not carstate.rightBlinker)
                        or (self._nav_signal_tail_direction == "right" and carstate.rightBlinker and not carstate.leftBlinker))
      if not tail_signal_on:
        self._nav_signal_tail_direction = None
        self._nav_signal_tail_turn_only = False

    nav_left = nav_signal and str(nav_lane_intent.direction) == "left"
    nav_right = nav_signal and str(nav_lane_intent.direction) == "right"
    physical_conflict = ((carstate.leftBlinker and nav_right) or (carstate.rightBlinker and nav_left))
    if physical_conflict:
      nav_signal = nav_left = nav_right = False
    suppress_turn_only_left = bool(
      ((self._active_nav_signal_turn_only and self._active_nav_signal_direction == "left")
       or self._nav_signal_tail_direction == "left") and carstate.leftBlinker and not carstate.rightBlinker
    )
    suppress_turn_only_right = bool(
      ((self._active_nav_signal_turn_only and self._active_nav_signal_direction == "right")
       or self._nav_signal_tail_direction == "right") and carstate.rightBlinker and not carstate.leftBlinker
    )
    left_blinker = bool((carstate.leftBlinker and not suppress_turn_only_left) or nav_left)
    right_blinker = bool((carstate.rightBlinker and not suppress_turn_only_right) or nav_right)
    one_blinker = left_blinker != right_blinker
    below_lane_change_speed = v_ego < LANE_CHANGE_SPEED_MIN

    # A navigation lane-change lamp must not look like an intersection turn to
    # LaneTurnDesire. Turn-only navigation lamps and driver lamps retain the
    # existing SP behavior.
    nav_lane_signal_left = bool(
      self._active_nav_signal_direction == "left" and not self._active_nav_signal_turn_only
    )
    nav_lane_signal_right = bool(
      self._active_nav_signal_direction == "right" and not self._active_nav_signal_turn_only
    )
    nav_lane_tail_left = bool(
      self._nav_signal_tail_direction == "left" and not self._nav_signal_tail_turn_only
    )
    nav_lane_tail_right = bool(
      self._nav_signal_tail_direction == "right" and not self._nav_signal_tail_turn_only
    )
    lane_turn_left_blinker = bool(carstate.leftBlinker and not (nav_lane_signal_left or nav_lane_tail_left))
    lane_turn_right_blinker = bool(carstate.rightBlinker and not (nav_lane_signal_right or nav_lane_tail_right))

    # Lane turn controller update
    self.lane_turn_controller.update_lane_turn(blindspot_left=carstate.leftBlindspot, blindspot_right=carstate.rightBlindspot,
                                               left_blinker=lane_turn_left_blinker,
                                               right_blinker=lane_turn_right_blinker, v_ego=v_ego)
    self.lane_turn_direction = self.lane_turn_controller.get_turn_direction()

    if (not lateral_active or self.lane_change_timer > LANE_CHANGE_TIME_MAX or
        self.alc.lane_change_set_timer == AutoLaneChangeMode.OFF):
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
      self.lane_change_timer = 0.0
    else:
      if self.lane_change_state == LaneChangeState.off and one_blinker and not self.prev_one_blinker and not below_lane_change_speed:
        self.lane_change_state = LaneChangeState.preLaneChange
        self.lane_change_timer = 0.0
        # Initialize lane change direction to prevent UI alert flicker
        self.lane_change_direction = self.get_lane_change_direction(left_blinker, right_blinker)

      elif self.lane_change_state == LaneChangeState.preLaneChange:
        # Update lane change direction
        self.lane_change_direction = self.get_lane_change_direction(left_blinker, right_blinker)

        torque_applied = carstate.steeringPressed and \
                         ((carstate.steeringTorque > 0 and self.lane_change_direction == LaneChangeDirection.left) or
                          (carstate.steeringTorque < 0 and self.lane_change_direction == LaneChangeDirection.right))

        left_blocked = carstate.leftBlindspot or left_edge_detected or left_line_blocked
        right_blocked = carstate.rightBlindspot or right_edge_detected or right_line_blocked
        blindspot_detected = ((left_blocked and self.lane_change_direction == LaneChangeDirection.left) or
                              (right_blocked and self.lane_change_direction == LaneChangeDirection.right))

        physical_nav_signal_on = bool(
          (nav_left and carstate.leftBlinker and not carstate.rightBlinker)
          or (nav_right and carstate.rightBlinker and not carstate.leftBlinker)
        )
        nav_crossing_allowed = bool(
          (nav_left and left_crossing_allowed) or (nav_right and right_crossing_allowed)
        )
        nav_not_ready = nav_signal and not (
          physical_nav_signal_on and nav_crossing_allowed and bool(getattr(nav_lane_intent, "spLaneChangeReady", False))
        )
        lane_change_blocked = blindspot_detected or nav_not_ready

        self.alc.update_lane_change(lane_change_blocked, carstate.brakePressed)

        if not one_blinker or below_lane_change_speed:
          self.lane_change_state = LaneChangeState.off
          self.lane_change_direction = LaneChangeDirection.none
          self.lane_change_timer = 0.0
        else:
          if (torque_applied or self.alc.auto_lane_change_allowed) and not lane_change_blocked:
            self.lane_change_state = LaneChangeState.laneChangeStarting
            self.lane_change_timer = 0.0

      elif self.lane_change_state == LaneChangeState.laneChangeStarting:
        self.lane_change_timer += DT_MDL

        if lane_change_prob < 0.02 and self.lane_change_timer >= LANE_CHANGE_START_TIME:
          self.lane_change_timer = 0.0
          if one_blinker:
            self.lane_change_state = LaneChangeState.preLaneChange
            self.lane_change_direction = self.get_lane_change_direction(left_blinker, right_blinker)
          else:
            self.lane_change_state = LaneChangeState.off
            self.lane_change_direction = LaneChangeDirection.none

    self.prev_one_blinker = one_blinker and lateral_active

    if self.lane_turn_direction != TurnDirection.none:
      self.desire = TURN_DESIRES[self.lane_turn_direction]
    else:
      self.desire = log.Desire.none
      if self.lane_change_state == LaneChangeState.laneChangeStarting:
        if self.lane_change_direction == LaneChangeDirection.left:
          self.desire = log.Desire.laneChangeLeft
        elif self.lane_change_direction == LaneChangeDirection.right:
          self.desire = log.Desire.laneChangeRight

    self.alc.update_state()
