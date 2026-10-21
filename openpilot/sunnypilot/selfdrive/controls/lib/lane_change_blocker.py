from __future__ import annotations


NON_CROSSABLE_EGO_MARKINGS = frozenset(("solid", "doubleSolid", "solidDashed", "roadEdge"))
SOLID_EGO_MARKINGS = frozenset(("solid", "doubleSolid", "solidDashed"))
CROSSABLE_EGO_MARKINGS = frozenset(("dashed", "doubleDashed"))


def nav_lane_crossing_policy(intent: object | None, side: str) -> tuple[bool, bool]:
  """Unknown paint is a directional lane policy; solid bypass additionally needs forkNow."""
  if side not in ("left", "right"):
    raise ValueError("side must be left or right")
  if (intent is None or not intent.valid or not intent.signalRequested  # type: ignore[attr-defined]
      or intent.targetLaneIndex < 0 or str(intent.direction) != side):  # type: ignore[attr-defined]
    return False, False
  return bool(intent.allowUnknownCrossing), bool(intent.forkNow and intent.ignoreSolidBoundary)  # type: ignore[attr-defined]


def lane_topology_change_blocks(topology: object, *, healthy: bool) -> tuple[bool, bool]:
  """Return reliable per-side lane-boundary vetoes for SP lane-change entry."""

  if not healthy or not bool(topology.validForControl):  # type: ignore[attr-defined]
    return False, False
  left = bool(
    topology.leftEvidenceValid  # type: ignore[attr-defined]
    and str(topology.leftEgoSideMarking) in NON_CROSSABLE_EGO_MARKINGS  # type: ignore[attr-defined]
  )
  right = bool(
    topology.rightEvidenceValid  # type: ignore[attr-defined]
    and str(topology.rightEgoSideMarking) in NON_CROSSABLE_EGO_MARKINGS  # type: ignore[attr-defined]
  )
  return left, right


def lane_topology_nav_crossing_allowed(topology: object, *, side: str, healthy: bool,
                                       allow_unknown: bool = False, ignore_solid: bool = False,
                                       nav_intent: object | None = None) -> bool:
  """Apply a bounded navigation crossing policy without bypassing stale geometry or road edges."""
  if side not in ("left", "right"):
    raise ValueError("side must be left or right")
  if nav_intent is not None:
    # The coordinator already checked visual geometry, fused crossing permission and health.
    # A confirmed road edge still vetoes; OEM positive may replace visual paint.
    ready = bool(
      nav_intent.valid and nav_intent.signalRequested and nav_intent.targetLaneIndex >= 0
      and str(nav_intent.direction) == side and nav_intent.spLaneChangeReady
    )
    vetoes = lane_topology_change_blocks(topology, healthy=healthy)
    marking = str(getattr(topology, f"{side}EgoSideMarking"))
    return ready and (not vetoes[0 if side == "left" else 1]
                      or (ignore_solid and marking in SOLID_EGO_MARKINGS))
  if not healthy or not bool(topology.validForControl):  # type: ignore[attr-defined]
    return False
  evidence_valid = bool(getattr(topology, f"{side}EvidenceValid"))
  marking = str(getattr(topology, f"{side}EgoSideMarking"))
  if evidence_valid:
    if marking in CROSSABLE_EGO_MARKINGS:
      return True
    if ignore_solid and marking in SOLID_EGO_MARKINGS:
      return True
    return False
  return allow_unknown


class LaneChangeBoundaryBlocker:
  """Hold a confirmed boundary until crossable visual evidence clears it.

  ``confirm_frames`` requires the same side to keep reporting a non-crossable
  boundary for that many consecutive model frames before it is allowed to
  veto a lane change; a single frame of solid paint is usually marking jitter
  or one noisy detection.
  """

  def __init__(self, *, clear_frames: int = 6, confirm_frames: int = 2):
    if clear_frames <= 0:
      raise ValueError("clear_frames must be positive")
    if confirm_frames <= 0:
      raise ValueError("confirm_frames must be positive")
    self.clear_frames = clear_frames
    self.confirm_frames = confirm_frames
    self._remaining = [0, 0]
    self._held_markings = ["unknown", "unknown"]
    self._streak = [0, 0]

  def reset(self) -> None:
    self._remaining = [0, 0]
    self._held_markings = ["unknown", "unknown"]
    self._streak = [0, 0]

  def update(self, topology: object, *, healthy: bool,
             ignore_left_solid: bool = False, ignore_right_solid: bool = False,
             allow_left_oem_solid: bool = False, allow_right_oem_solid: bool = False) -> tuple[bool, bool]:
    immediate = lane_topology_change_blocks(topology, healthy=healthy)
    blocked = [False, False]
    ignored = (ignore_left_solid, ignore_right_solid)
    oem_allowed = (allow_left_oem_solid, allow_right_oem_solid)
    for side, detected in enumerate(immediate):
      # Debounce: a boundary only counts after confirm_frames consecutive frames.
      self._streak[side] = self._streak[side] + 1 if detected else 0
      confirmed = self._streak[side] >= self.confirm_frames
      if confirmed:
        self._remaining[side] = self.clear_frames
        self._held_markings[side] = str(
          topology.leftEgoSideMarking if side == 0 else topology.rightEgoSideMarking  # type: ignore[attr-defined]
        )
      if ignored[side] and self._held_markings[side] in SOLID_EGO_MARKINGS:
        confirmed = False
        self._remaining[side] = 0
        self._held_markings[side] = "unknown"
        self._streak[side] = 0
      elif not confirmed and self._remaining[side] > 0:
        prefix = "left" if side == 0 else "right"
        crossable = (healthy and bool(topology.validForControl)
                     and bool(getattr(topology, prefix + "EvidenceValid"))
                     and str(getattr(topology, prefix + "EgoSideMarking")) in CROSSABLE_EGO_MARKINGS)
        self._remaining[side] = self._remaining[side] - 1 if crossable else self.clear_frames
        if self._remaining[side] == 0:
          self._held_markings[side] = "unknown"
      blocked[side] = (confirmed or self._remaining[side] > 0) and not (
        oem_allowed[side] and self._held_markings[side] in SOLID_EGO_MARKINGS)
    return blocked[0], blocked[1]


if __name__ == '__main__':
  class _Topo:
    def __init__(self, left: str | None = None, right: str | None = None):
      self.valid = True
      self.validForControl = True
      self.leftEvidenceValid = left is not None
      self.rightEvidenceValid = right is not None
      self.leftEgoSideMarking = left or 'unknown'
      self.rightEgoSideMarking = right or 'unknown'
      self.leftNeighborExists = left in CROSSABLE_EGO_MARKINGS
      self.rightNeighborExists = right in CROSSABLE_EGO_MARKINGS

  blk = LaneChangeBoundaryBlocker()
  first = blk.update(_Topo('solid', 'dashed'), healthy=True)
  second = blk.update(_Topo('solid', 'dashed'), healthy=True)
  third = blk.update(_Topo('solid', 'dashed'), healthy=True)
  print(f'  单帧 solid: {first}  (期望 (False, False))')
  print(f'  连续第 2 帧: {second}  (期望 (True, False))')
  print(f'  连续第 3 帧: {third}  (期望 (True, False))')

  cleared = None
  for _ in range(6):
    cleared = blk.update(_Topo('dashed', 'dashed'), healthy=True)
  print(f'  连续 6 帧 dashed 后: {cleared}  (期望 (False, False))')

  ok = first == (False, False) and second == (True, False) and third == (True, False) and cleared == (False, False)
  print('self test:', 'PASS' if ok else 'FAIL')
