"""Absolute same-direction lane index; visible-only evidence is never enough.

The display path (:mod:`openpilot.sunnypilot.lane_topology.geometry`) reports the
lanes an observer can currently see. An absolute index additionally needs proof
that the observed set spans the *whole* same-direction carriageway: both outer
boundaries must be identified and typed as carriageway edges, no boundary may sit
outside them, every interior space must be a plausible single lane, and the same
answer must repeat over consecutive fresh frames.

Nothing here can produce a number on its own. If any piece of that evidence is
missing the decision is ``valid=False``, which is the only honest answer for a
locally visible "1/1" corridor. The module is pure geometry and state: it does
not read the camera, the model, parameters or vehicle state, and it is not wired
into any live producer.
"""
from __future__ import annotations

from dataclasses import dataclass

from openpilot.sunnypilot.lane_topology.geometry import (
  MAX_LANE_WIDTH_M,
  MIN_LANE_WIDTH_M,
  SAMPLE_X_M,
  interpolate_y,
)
from openpilot.sunnypilot.lane_topology.types import (
  LaneBoundary,
  LaneMarkingType,
  LaneTopologyState,
)

MAX_ABSOLUTE_LANE_INDEX = 12
DEFAULT_MIN_CONFIDENCE = 0.35
DEFAULT_MIN_STABLE_SAMPLES = 3
DEFAULT_MAX_GAP_NS = 700_000_000

# A same-direction carriageway starts at a road edge, a median/central barrier,
# or the opposing-direction separation (a double line). The right side is
# normally the shoulder edge line; accepting a loose solid line there would let a
# lane divider masquerade as the carriageway end.
LEFT_EDGE_MARKINGS = frozenset((LaneMarkingType.roadEdge, LaneMarkingType.doubleSolid))
RIGHT_EDGE_MARKINGS = frozenset((LaneMarkingType.roadEdge,))


@dataclass(frozen=True)
class AbsoluteLaneDecision:
  """One frame's absolute conclusion, or an explicit unknown with a reason."""

  valid: bool
  lane_index: int | None
  lane_count: int | None
  stable_samples: int
  capture_mono_ns: int
  reason: str

  @classmethod
  def unknown(cls, reason: str, *, stable_samples: int = 0, capture_mono_ns: int = 0) -> AbsoluteLaneDecision:
    return cls(False, None, None, stable_samples, capture_mono_ns, reason)


def explicit_carriageway_edges(boundaries: tuple[LaneBoundary, ...], *,
                               sample_x_m: float = SAMPLE_X_M) -> tuple[int, int] | None:
  """Return ``(left_track_id, right_track_id)`` only for unambiguous edges.

  The outermost observed boundaries must themselves be typed carriageway edges.
  If any observed boundary lies outside them the carriageway is not fully
  spanned, so there is no absolute answer and ``None`` is returned.
  """

  positioned: list[tuple[float, LaneBoundary]] = []
  for boundary in boundaries:
    if not boundary.visible:
      continue
    y = interpolate_y(boundary.points, sample_x_m)
    if y is not None:
      positioned.append((y, boundary))
  if len(positioned) < 2:
    return None
  positioned.sort(key=lambda item: item[0], reverse=True)
  left, right = positioned[0][1], positioned[-1][1]
  if left.track_id == right.track_id:
    return None
  if left.marking_type not in LEFT_EDGE_MARKINGS or right.marking_type not in RIGHT_EDGE_MARKINGS:
    return None
  return left.track_id, right.track_id


class AbsoluteLaneGate:
  """Requires complete, typed, repeated carriageway evidence before answering."""

  def __init__(self, *, min_stable_samples: int = DEFAULT_MIN_STABLE_SAMPLES,
               max_gap_ns: int = DEFAULT_MAX_GAP_NS, min_confidence: float = DEFAULT_MIN_CONFIDENCE,
               min_lane_width_m: float = MIN_LANE_WIDTH_M, max_lane_width_m: float = MAX_LANE_WIDTH_M,
               sample_x_m: float = SAMPLE_X_M):
    if min_stable_samples < 1:
      raise ValueError('min_stable_samples must be positive')
    if not 0 < max_gap_ns:
      raise ValueError('max_gap_ns must be positive')
    if not 0.0 <= min_confidence <= 1.0:
      raise ValueError('min_confidence must be within [0, 1]')
    if not 0.0 < min_lane_width_m < max_lane_width_m:
      raise ValueError('invalid lane width bounds')
    self.min_stable_samples = min_stable_samples
    self.max_gap_ns = max_gap_ns
    self.min_confidence = min_confidence
    self.min_lane_width_m = min_lane_width_m
    self.max_lane_width_m = max_lane_width_m
    self.sample_x_m = sample_x_m
    self.reset()

  def reset(self) -> None:
    """Drop every retained conclusion; the next answer needs fresh evidence."""
    self._key: tuple[int, int] | None = None
    self._count = 0
    self._identity: tuple[str, int] | None = None
    self._last_ns: int | None = None

  def update(self, boundaries: tuple[LaneBoundary, ...], *, left_edge_track_id: int, right_edge_track_id: int,
             frame_id: int, timestamp_ns: int, session_id: str, route_revision: int,
             topology_state: LaneTopologyState = LaneTopologyState.normal,
             ego_y_m: float = 0.0) -> AbsoluteLaneDecision:
    del frame_id  # recorded by the caller; identity here is session plus route
    identity = (session_id, route_revision)
    if identity != self._identity:
      self.reset()
      self._identity = identity
    if self._last_ns is not None and not 0 < timestamp_ns - self._last_ns <= self.max_gap_ns:
      # A repeated clock, a backward clock or a long gap all invalidate stability.
      self._key, self._count = None, 0
    self._last_ns = timestamp_ns

    def reject(reason: str) -> AbsoluteLaneDecision:
      self._key, self._count = None, 0
      return AbsoluteLaneDecision.unknown(reason, capture_mono_ns=timestamp_ns)

    if topology_state != LaneTopologyState.normal:
      return reject(f'topology:{topology_state.name}')
    if left_edge_track_id == right_edge_track_id:
      return reject('degenerateCarriageway')

    positioned: list[tuple[float, LaneBoundary]] = []
    for boundary in boundaries:
      y = interpolate_y(boundary.points, self.sample_x_m)
      if y is not None:
        positioned.append((y, boundary))
    positioned.sort(key=lambda item: item[0], reverse=True)
    ordered = [boundary for _, boundary in positioned]
    if len(ordered) < 2:
      return reject('insufficientBoundaries')

    track_ids = [boundary.track_id for boundary in ordered]
    if left_edge_track_id not in track_ids or right_edge_track_id not in track_ids:
      return reject('carriagewayEdgeNotObserved')
    left_index, right_index = track_ids.index(left_edge_track_id), track_ids.index(right_edge_track_id)
    if left_index >= right_index:
      return reject('carriagewayEdgesNotOrdered')
    # Any observed boundary outside the claimed edges means at least one lane is
    # unaccounted for, so the count cannot be absolute.
    if left_index != 0 or right_index != len(ordered) - 1:
      return reject('boundaryOutsideCarriageway')

    span = ordered[left_index:right_index + 1]
    # The caller's edge claim is not authority: the boundary itself must be typed
    # as a carriageway edge, otherwise a lane divider could pass as the road end.
    if span[0].marking_type not in LEFT_EDGE_MARKINGS or span[-1].marking_type not in RIGHT_EDGE_MARKINGS:
      return reject('edgeMarkingNotConfirmed')
    if any(not boundary.visible for boundary in span):
      return reject('interiorBoundaryNotVisible')
    if any(not boundary.confidence >= self.min_confidence for boundary in span):
      return reject('lowConfidenceBoundary')

    ys = [interpolate_y(boundary.points, self.sample_x_m) for boundary in span]
    spaces: list[tuple[int, float, float]] = []
    for offset, (left_y, right_y) in enumerate(zip(ys, ys[1:], strict=False)):
      width = float(left_y) - float(right_y)
      if not self.min_lane_width_m <= width <= self.max_lane_width_m:
        # A missing interior line merges two lanes into one over-wide space; a
        # double-counted line splits one into an implausible narrow space.
        return reject('implausibleLaneWidth')
      spaces.append((left_index + offset, float(left_y), float(right_y)))
    if not spaces:
      return reject('insufficientBoundaries')

    ego_space = None
    for space_index, left_y, right_y in spaces:
      if left_y > ego_y_m > right_y:
        ego_space = space_index
        break
    if ego_space is None:
      return reject('egoOutsideCarriageway')

    lane_count = len(spaces)
    lane_index = ego_space - left_index + 1
    if not 1 <= lane_index <= lane_count <= MAX_ABSOLUTE_LANE_INDEX:
      return reject('laneRangeExceeded')

    key = (lane_index, lane_count)
    self._count = self._count + 1 if key == self._key else 1
    self._key = key
    if self._count < self.min_stable_samples:
      return AbsoluteLaneDecision.unknown('stabilizing', stable_samples=self._count,
                                          capture_mono_ns=timestamp_ns)
    return AbsoluteLaneDecision(True, lane_index, lane_count, self._count, timestamp_ns, 'absoluteConfirmed')


class RightEdgeAnchoredGate:
  """Absolute index from a confirmed right carriageway edge plus a map total.

  Requiring both carriageway edges is what the shipped gate does, and on real
  wide-camera frames the left one is the boundary that is never found: it is the
  median or the opposing-direction separation, and a leading vehicle hides it
  exactly where it matters. The right edge is the shoulder line, and that is the
  boundary real observers do trace.

  So this gate anchors on the right edge alone and takes the total from the
  navigation lane guidance, which is authoritative for how many same-direction
  lanes exist but says nothing about where the ego sits. Vision supplies the
  anchor, the map supplies the count; neither is asked to do the other's job.

  It still refuses whenever the anchor is unconfirmed, whenever an interior line
  between the ego and the right edge is missing, and whenever the count implied
  by the anchor contradicts the map total.
  """

  def __init__(self, *, min_stable_samples: int = DEFAULT_MIN_STABLE_SAMPLES,
               max_gap_ns: int = DEFAULT_MAX_GAP_NS, min_confidence: float = DEFAULT_MIN_CONFIDENCE,
               min_lane_width_m: float = MIN_LANE_WIDTH_M, max_lane_width_m: float = MAX_LANE_WIDTH_M,
               sample_x_m: float = SAMPLE_X_M):
    if min_stable_samples < 1:
      raise ValueError('min_stable_samples must be positive')
    if not 0 < max_gap_ns:
      raise ValueError('max_gap_ns must be positive')
    if not 0.0 <= min_confidence <= 1.0:
      raise ValueError('min_confidence must be within [0, 1]')
    if not 0.0 < min_lane_width_m < max_lane_width_m:
      raise ValueError('invalid lane width bounds')
    self.min_stable_samples = min_stable_samples
    self.max_gap_ns = max_gap_ns
    self.min_confidence = min_confidence
    self.min_lane_width_m = min_lane_width_m
    self.max_lane_width_m = max_lane_width_m
    self.sample_x_m = sample_x_m
    self.reset()

  def reset(self) -> None:
    self._key: tuple[int, int] | None = None
    self._count = 0
    self._identity: tuple[str, int] | None = None
    self._last_ns: int | None = None

  def update(self, boundaries: tuple[LaneBoundary, ...], *, right_edge_track_id: int,
             lane_total: int | None, frame_id: int, timestamp_ns: int, session_id: str,
             route_revision: int, topology_state: LaneTopologyState = LaneTopologyState.normal,
             ego_y_m: float = 0.0) -> AbsoluteLaneDecision:
    del frame_id  # recorded by the caller; identity here is session plus route
    identity = (session_id, route_revision)
    if identity != self._identity:
      self.reset()
      self._identity = identity
    if self._last_ns is not None and not 0 < timestamp_ns - self._last_ns <= self.max_gap_ns:
      self._key, self._count = None, 0
    self._last_ns = timestamp_ns

    def reject(reason: str) -> AbsoluteLaneDecision:
      self._key, self._count = None, 0
      return AbsoluteLaneDecision.unknown(reason, capture_mono_ns=timestamp_ns)

    # The map total is a requirement, not a hint: without it the anchor says how
    # far the ego is from the shoulder, not which lane that is.
    if type(lane_total) is not int or not 1 <= lane_total <= MAX_ABSOLUTE_LANE_INDEX:
      return reject('laneTotalUnavailable')
    if topology_state != LaneTopologyState.normal:
      return reject(f'topology:{topology_state.name}')

    positioned: list[tuple[float, LaneBoundary]] = []
    for boundary in boundaries:
      y = interpolate_y(boundary.points, self.sample_x_m)
      if y is not None:
        positioned.append((y, boundary))
    positioned.sort(key=lambda item: item[0], reverse=True)
    ordered = [boundary for _, boundary in positioned]
    track_ids = [boundary.track_id for boundary in ordered]
    if right_edge_track_id not in track_ids:
      return reject('carriagewayEdgeNotObserved')
    right_index = track_ids.index(right_edge_track_id)
    # Anything observed to the right of the claimed edge leaves a lane unaccounted.
    if right_index != len(ordered) - 1:
      return reject('boundaryOutsideCarriageway')
    if ordered[right_index].marking_type not in RIGHT_EDGE_MARKINGS:
      return reject('edgeMarkingNotConfirmed')
    if not ordered[right_index].visible:
      return reject('edgeNotVisible')
    if not ordered[right_index].confidence >= self.min_confidence:
      return reject('lowConfidenceBoundary')

    # Every boundary strictly right of the ego is one more lane to its right.
    to_the_right = [boundary for boundary in ordered[right_index::-1]
                    if boundary.track_id != right_edge_track_id
                    and float(interpolate_y(boundary.points, self.sample_x_m)) < ego_y_m]
    if any(not boundary.visible for boundary in to_the_right):
      return reject('interiorBoundaryNotVisible')
    if any(not boundary.confidence >= self.min_confidence for boundary in to_the_right):
      return reject('lowConfidenceBoundary')

    right_edge_y = float(interpolate_y(ordered[right_index].points, self.sample_x_m))
    interior = sorted((float(interpolate_y(boundary.points, self.sample_x_m))
                       for boundary in to_the_right), reverse=True)
    ladder = [float(ego_y_m), *interior, right_edge_y]
    gaps = [ladder[index] - ladder[index + 1] for index in range(len(ladder) - 1)]
    # The ego may sit anywhere inside its lane, so only the first gap is unbounded
    # below. Gaps between real lane lines must be single lane widths: a missing
    # line reads as an over-wide gap and a double-counted line as a narrow one.
    if not 0.0 < gaps[0] <= self.max_lane_width_m:
      return reject('implausibleLaneWidth')
    if any(not self.min_lane_width_m <= gap <= self.max_lane_width_m for gap in gaps[1:]):
      return reject('implausibleLaneWidth')

    lanes_to_the_right = len(to_the_right)
    if lanes_to_the_right > lane_total - 1:
      return reject('mapTotalInconsistent')
    lane_index = lane_total - lanes_to_the_right
    if not 1 <= lane_index <= lane_total <= MAX_ABSOLUTE_LANE_INDEX:
      return reject('laneRangeExceeded')

    key = (lane_index, lane_total)
    self._count = self._count + 1 if key == self._key else 1
    self._key = key
    if self._count < self.min_stable_samples:
      return AbsoluteLaneDecision.unknown('stabilizing', stable_samples=self._count,
                                          capture_mono_ns=timestamp_ns)
    return AbsoluteLaneDecision(True, lane_index, lane_total, self._count, timestamp_ns, 'absoluteConfirmed')
