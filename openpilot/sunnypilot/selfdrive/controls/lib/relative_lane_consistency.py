from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RelativeLaneStatus:
  ready: bool
  edge_confirmed: bool
  completed_changes: int
  reason: str


class RelativeLaneConsistencyFilter:
  """Temporal consistency for one-direction-at-a-time relative edge alignment."""

  def __init__(self, *, presence_stable_ns: int = 500_000_000,
               edge_stable_ns: int = 5_000_000_000,
               new_lane_stable_ns: int = 3_000_000_000,
               cooldown_ns: int = 2_000_000_000,
               max_changes: int = 5):
    values = (presence_stable_ns, edge_stable_ns, new_lane_stable_ns, cooldown_ns)
    if any(value < 0 for value in values) or max_changes <= 0:
      raise ValueError("relative lane consistency limits must be non-negative")
    self.presence_stable_ns = presence_stable_ns
    self.edge_stable_ns = edge_stable_ns
    self.new_lane_stable_ns = new_lane_stable_ns
    self.cooldown_ns = cooldown_ns
    self.max_changes = max_changes
    self._event_direction: tuple[tuple[str, int, int], str] | None = None
    self._presence_since_ns: int | None = None
    self._absence_since_ns: int | None = None
    self._edge_confirmed = False
    self._completed_changes = 0
    self._cooldown_until_ns = 0

  def _status(self, ready: bool, reason: str) -> RelativeLaneStatus:
    return RelativeLaneStatus(ready, self._edge_confirmed, self._completed_changes, reason)

  def _reset_event(self, event_key: tuple[str, int, int], direction: str) -> None:
    self._event_direction = (event_key, direction)
    self._presence_since_ns = None
    self._absence_since_ns = None
    self._edge_confirmed = False
    self._completed_changes = 0
    self._cooldown_until_ns = 0

  def update(self, event_key: tuple[str, int, int], *, direction: str,
             neighbor_exists: bool | None, observation_valid: bool,
             lane_change_active: bool, steering_pressed: bool,
             now_ns: int) -> RelativeLaneStatus:
    if direction not in ("left", "right"):
      raise ValueError("relative lane direction must be left or right")
    if now_ns < 0:
      raise ValueError("now_ns must be non-negative")
    if self._event_direction != (event_key, direction):
      self._reset_event(event_key, direction)

    if not observation_valid:
      self._presence_since_ns = None
      self._absence_since_ns = None
      return self._status(False, "observationInvalid")
    if lane_change_active:
      self._presence_since_ns = None
      self._absence_since_ns = None
      return self._status(False, "laneChangeTransition")
    if steering_pressed:
      self._presence_since_ns = None
      self._absence_since_ns = None
      return self._status(False, "driverSteering")

    # Missing outer paint is not evidence that the road ends. Keep confirmed
    # history, but never accumulate presence/absence time from unknown frames.
    if neighbor_exists is None:
      self._presence_since_ns = None
      self._absence_since_ns = None
      return self._status(False, "neighborUnknown")

    if not neighbor_exists:
      self._presence_since_ns = None
      if self._absence_since_ns is None:
        self._absence_since_ns = now_ns
      if now_ns - self._absence_since_ns >= self.edge_stable_ns:
        self._edge_confirmed = True
        return self._status(False, "edgeConfirmed")
      return self._status(False, "stabilizingEdge")

    self._absence_since_ns = None
    if self._presence_since_ns is None:
      self._presence_since_ns = now_ns
    if self._completed_changes >= self.max_changes:
      return self._status(False, "changeLimit")
    if now_ns < self._cooldown_until_ns:
      return self._status(False, "cooldown")
    stable_ns = self.new_lane_stable_ns if self._edge_confirmed else self.presence_stable_ns
    if now_ns - self._presence_since_ns < stable_ns:
      return self._status(False, "stabilizingNewNeighbor" if self._edge_confirmed else "stabilizingNeighbor")

    was_edge_confirmed = self._edge_confirmed
    self._edge_confirmed = False
    return self._status(True, "newNeighborStable" if was_edge_confirmed else "neighborStable")

  def note_lane_change_completed(self, now_ns: int) -> None:
    if self._event_direction is None:
      return
    self._completed_changes += 1
    self._cooldown_until_ns = now_ns + self.cooldown_ns
    self._presence_since_ns = None
    self._absence_since_ns = None
    self._edge_confirmed = False
