"""Fuse an absolute ego-lane position from AMap lane count and C3 vision anchors.

This module is deliberately pure: it takes already-validated numbers and
returns a typed answer.  It never reads a message, a clock, or a vehicle bus.

The idea is the one the phone navigation already relies on:

* AMap knows how many lanes the road has (the app sends one item per lane);
* C3 vision knows where the ego sits inside the *visible window*, and whether
  that window is anchored to a physical carriageway edge (road edge) or to the
  opposing-traffic centreline (double yellow);
* the two only combine when the anchor makes the visible count meaningful.

Nothing here equates a lane index with a recommendation, a model trajectory, or
a lane-change intent.  When the anchor or the count is missing the answer is
unknown, not a default of 1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from openpilot.sunnypilot.lane_topology.types import LaneMarkingType

MAX_LANES = 16
ANCHORS = frozenset(("unknown", "roadEdge", "centerline"))
LANE_TOPOLOGY_MAX_AGE_NS = 150_000_000
LANE_NAV_MAX_AGE_NS = 2_000_000_000
ANCHOR_HOLD_MAX_NS = 1_000_000_000
ANCHOR_HOLD_MIN_SPEED_MPS = 1.0
HOLDABLE_REASONS = frozenset(("noSameDirectionAnchor", "amapLaneCountUnknown", "topologyUnavailable", "visibleGeometryInvalid"))


@dataclass(frozen=True)
class LanePosition:
  valid: bool
  lane_index_from_left: int | None
  lane_number_from_left: int | None
  lane_count: int | None
  confidence: float
  basis: str
  reason: str | None
  source: str
  held: bool = False
  held_for_ms: float = 0.0

  def to_dict(self) -> dict:
    return asdict(self)


def _unknown(reason: str, *, basis: str = "none") -> LanePosition:
  return LanePosition(False, None, None, None, 0.0, basis, reason, "vision")


def empty_lane_position(reason: str = "notComputed") -> dict:
  """Fully shaped unknown for the period before the first message arrives."""
  return _unknown(reason).to_dict()


def amap_lane_count(indices, total: int | None = None) -> int | None:
  """Return N from an explicit App count, else from a complete 0..N-1 set.

  AMap can describe the whole road while the App sends only a window of it, so
  an explicit ``totalCount`` (already bounded by the parser) is preferred.  A
  bare list of four items with a hole is not proof of four lanes; a sparse or
  duplicated index set is reported as unknown rather than guessed from length.
  """
  try:
    values = [int(index) for index in indices]
  except (TypeError, ValueError):
    return None
  if type(total) is int and 1 <= total <= MAX_LANES:
    if len(set(values)) != len(values):
      return None
    if any(not 0 <= index < total for index in values):
      return None
    return total
  if not values or len(values) > MAX_LANES:
    return None
  if len(set(values)) != len(values):
    return None
  if sorted(values) != list(range(len(values))):
    return None
  return len(values)


def estimate_ego_lane(*, amap_lane_indices=(),
                      amap_total_count: int | None = None,
                      visible_lane_count: int = 0,
                      ego_visible_index: int = -1,
                      lanes_left_same_direction: int = -1,
                      lanes_right_same_direction: int = -1,
                      left_anchor: str = "unknown",
                      right_anchor: str = "unknown",
                      topology_fresh: bool = False,
                      topology_valid: bool = False) -> LanePosition:
  """Return the ego lane from the left, or a reason why it is unknown."""
  if left_anchor not in ANCHORS or right_anchor not in ANCHORS:
    return _unknown("invalidAnchor")
  if right_anchor == "centerline":
    # A centreline on the ego's right means the ego is on the opposing side;
    # a lane number from that geometry would be wrong-way advice.
    return _unknown("rightCenterlineInvalid")
  if not topology_fresh or not topology_valid:
    return _unknown("topologyUnavailable")
  if (type(visible_lane_count) is not int or type(ego_visible_index) is not int
      or not 1 <= visible_lane_count <= MAX_LANES
      or not 0 <= ego_visible_index < visible_lane_count):
    return _unknown("visibleGeometryInvalid")

  left = lanes_left_same_direction if left_anchor != "unknown" else -1
  right = lanes_right_same_direction if right_anchor != "unknown" else -1
  if left < -1 or right < -1:
    return _unknown("anchorCountInvalid")
  if left >= 0 and right >= 0 and left + 1 + right != visible_lane_count:
    return _unknown("visibleCountMismatch")
  if left >= 0 and left >= visible_lane_count:
    return _unknown("leftAnchorExceedsWindow")
  if right >= 0 and right >= visible_lane_count:
    return _unknown("rightAnchorExceedsWindow")

  count = amap_lane_count(amap_lane_indices, amap_total_count)
  edge_total = left + 1 + right if left >= 0 and right >= 0 else None
  count_source = "amap"
  if edge_total is not None:
    if count is None:
      # Both physical edges bound the visible window: on a closed, one-way
      # carriageway that window is the whole road, so the camera alone knows
      # the total.  This is the highway case AMap may not supply.
      count, count_source = edge_total, "vision"
    elif count != edge_total:
      return _unknown("totalConflict")
  candidates: list[tuple[int, str, float]] = []
  if left >= 0:
    candidates.append((left, "left", 0.95 if left_anchor == "roadEdge" else 0.8))
  if right >= 0 and count is not None:
    candidates.append((count - 1 - right, "right", 0.9 if right_anchor == "roadEdge" else 0.75))

  if not candidates:
    if right >= 0 and count is None:
      return _unknown("amapLaneCountUnknown", basis="rightAnchorNeedsCount")
    return _unknown("noSameDirectionAnchor")

  indexes = {candidate[0] for candidate in candidates}
  if len(indexes) != 1:
    return _unknown("anchorConflict")
  index = indexes.pop()
  if index < 0:
    return _unknown("indexNegative")
  if count is not None and index >= count:
    return _unknown("indexExceedsAmapCount")

  if len(candidates) == 2:
    road_edges = left_anchor == "roadEdge" and right_anchor == "roadEdge"
    confidence = 0.9 if road_edges and count_source == "vision" else 0.95
    basis = "bothRoadEdges" if road_edges else "leftAndRightAgree"
  elif candidates[0][1] == "left":
    confidence = candidates[0][2]
    basis = "leftRoadEdge" if left_anchor == "roadEdge" else "leftCenterline"
  else:
    confidence = candidates[0][2]
    basis = "rightRoadEdge" if right_anchor == "roadEdge" else "rightCenterline"

  if count is None:
    source = "vision"
    basis += "+countUnknown"
    confidence = min(confidence, 0.8)
  elif count_source == "vision":
    source = "vision"
    basis += "+edgeTotal"
  else:
    source = "vision+amap"
    basis += "+amapCount"

  return LanePosition(
    valid=True,
    lane_index_from_left=index,
    lane_number_from_left=index + 1,
    lane_count=count,
    confidence=round(confidence, 3),
    basis=basis,
    reason=None,
    source=source,
  )

def same_direction_lane_anchors(topology) -> tuple[int, int, str, str]:
  """Count same-direction lanes from a physical window anchor.

  A double-yellow immediately left of the ego starts the same-direction
  carriageway (opposing traffic is beyond it); a road edge only does so when no
  centreline lies between it and the ego.  A right-side centreline means the
  ego is on the opposing side, so the right window is not anchored there.
  ``-1`` means no anchor, never "zero lanes".
  """
  index = topology.ego_lane_index_from_left
  types = [boundary.marking_type for boundary in topology.boundaries]
  if not 0 <= index < len(topology.spaces) or len(types) != len(topology.spaces) + 1:
    return -1, -1, "unknown", "unknown"

  # Nearest anchor at or left of the ego's left boundary wins: a road edge
  # immediately left of the ego is a stronger start than a centreline further
  # out, and a centreline further out than the ego's own boundary still counts
  # the lanes between it and the ego.  Lines beyond the edge are ignored.
  left_count, left_source = -1, "unknown"
  for boundary_index in range(index, -1, -1):
    marking = types[boundary_index]
    if marking == LaneMarkingType.roadEdge:
      left_count, left_source = index - boundary_index, "roadEdge"
      break
    if marking == LaneMarkingType.doubleSolid:
      left_count, left_source = index - boundary_index, "centerline"
      break

  # Walk outward to the right; a centreline before the road edge means the ego
  # would be looking across opposing traffic, so the right window is unanchored.
  right_count, right_source = -1, "unknown"
  for boundary_index in range(index + 1, len(types)):
    marking = types[boundary_index]
    if marking == LaneMarkingType.doubleSolid:
      break
    if marking == LaneMarkingType.roadEdge:
      right_count, right_source = boundary_index - 1 - index, "roadEdge"
      break
  return left_count, right_count, left_source, right_source


def lane_position_from_messages(nav, topology, *, now_ns: int, nav_mono_ns: int, topology_mono_ns: int,
                                nav_available: bool = True, topology_available: bool = True) -> dict:
  """Adapt the two cereal messages to :func:`estimate_ego_lane`.

  Kept free of ``messaging`` imports so the fusion can be tested with plain
  objects.  A stale phone snapshot drops the count but still allows a
  vision-only index when the window is physically anchored.
  """
  nav_fresh = bool(nav_available and nav is not None and nav.valid and not nav.stale
                   and 0 <= now_ns - nav_mono_ns <= LANE_NAV_MAX_AGE_NS)
  topology_fresh = bool(topology_available and topology is not None
                        and 0 <= now_ns - topology_mono_ns <= LANE_TOPOLOGY_MAX_AGE_NS)
  topology_valid = bool(topology_fresh and topology.valid and not topology.stale and not topology.ambiguous)
  lanes = tuple(int(lane.index) for lane in nav.lanes) if nav_fresh else ()
  total = int(nav.laneCount) if nav_fresh and hasattr(nav, "laneCount") else -1
  return estimate_ego_lane(
    amap_lane_indices=lanes,
    amap_total_count=total if 1 <= total <= MAX_LANES else None,
    visible_lane_count=int(topology.visibleLaneCount) if topology_available else 0,
    ego_visible_index=int(topology.egoLaneIndexFromLeft) if topology_available else -1,
    lanes_left_same_direction=int(topology.lanesLeftSameDirection) if topology_available else -1,
    lanes_right_same_direction=int(topology.lanesRightSameDirection) if topology_available else -1,
    left_anchor=str(topology.leftAnchorSource) if topology_available else "unknown",
    right_anchor=str(topology.rightAnchorSource) if topology_available else "unknown",
    topology_fresh=topology_fresh,
    topology_valid=topology_valid,
  ).to_dict()


class AnchorMemory:
  """Bridge brief anchor dropouts, never a whole exit.

  A last known position is reused only while the topology is still valid but
  the physical anchor vanished (``noSameDirectionAnchor``).  Contradictions,
  stale topology, a new session/route, standstill, and any hold older than
  ``max_hold_ns`` drop it immediately.  The held answer is marked, decays in
  confidence, and is never silently promoted to a fresh observation.
  """

  def __init__(self, *, max_hold_ns: int = ANCHOR_HOLD_MAX_NS,
               min_speed_mps: float = ANCHOR_HOLD_MIN_SPEED_MPS):
    self.max_hold_ns = int(max_hold_ns)
    self.min_speed_mps = float(min_speed_mps)
    self.reset()

  def reset(self) -> None:
    self._last: dict | None = None
    self._last_ns = 0
    self._session: str | None = None
    self._route: int | None = None

  def update(self, current: dict, *, now_ns: int, session_id: str, route_revision: int,
             speed_mps: float) -> dict:
    if current.get("valid") is True:
      self._last = dict(current)
      self._last_ns = now_ns
      self._session = session_id
      self._route = route_revision
      return dict(current)
    if self._last is None:
      return dict(current)
    if session_id != self._session or route_revision != self._route:
      self.reset()
      return dict(current)
    if not (speed_mps >= self.min_speed_mps):
      self.reset()
      return dict(current)
    age_ns = now_ns - self._last_ns
    if not 0 <= age_ns <= self.max_hold_ns:
      self.reset()
      return dict(current)
    if current.get("reason") not in HOLDABLE_REASONS:
      self.reset()
      return dict(current)
    age = age_ns / self.max_hold_ns
    held = dict(self._last)
    held["held"] = True
    held["held_for_ms"] = round(age_ns / 1e6, 1)
    held["confidence"] = round(max(0.0, float(held["confidence"]) * (1.0 - 0.5 * age)), 3)
    held["basis"] = str(held["basis"]) + "+held"
    return held
