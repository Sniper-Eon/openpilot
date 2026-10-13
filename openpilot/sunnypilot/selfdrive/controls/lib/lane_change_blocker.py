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
                                       allow_unknown: bool = False, ignore_solid: bool = False) -> bool:
  """Apply a bounded navigation crossing policy without bypassing stale geometry or road edges."""
  if side not in ("left", "right"):
    raise ValueError("side must be left or right")
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
  """Road-edge-style entry veto with a short clear grace after confirmed solid."""

  def __init__(self, *, clear_frames: int = 6):
    if clear_frames <= 0:
      raise ValueError("clear_frames must be positive")
    self.clear_frames = clear_frames
    self._remaining = [0, 0]
    self._held_markings = ["unknown", "unknown"]

  def reset(self) -> None:
    self._remaining = [0, 0]
    self._held_markings = ["unknown", "unknown"]

  def update(self, topology: object, *, healthy: bool,
             ignore_left_solid: bool = False, ignore_right_solid: bool = False) -> tuple[bool, bool]:
    immediate = lane_topology_change_blocks(topology, healthy=healthy)
    blocked = [False, False]
    ignored = (ignore_left_solid, ignore_right_solid)
    for side, detected in enumerate(immediate):
      if detected:
        self._remaining[side] = self.clear_frames
        self._held_markings[side] = str(
          topology.leftEgoSideMarking if side == 0 else topology.rightEgoSideMarking  # type: ignore[attr-defined]
        )
      if ignored[side] and self._held_markings[side] in SOLID_EGO_MARKINGS:
        detected = False
        self._remaining[side] = 0
        self._held_markings[side] = "unknown"
      elif not detected and self._remaining[side] > 0:
        self._remaining[side] -= 1
        if self._remaining[side] == 0:
          self._held_markings[side] = "unknown"
      blocked[side] = detected or self._remaining[side] > 0
    return blocked[0], blocked[1]
