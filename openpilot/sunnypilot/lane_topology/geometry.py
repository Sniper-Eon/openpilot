from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from openpilot.sunnypilot.lane_topology.types import (
  LaneBoundary,
  LaneBoundaryObservation,
  LaneMarkingType,
  LaneSpace,
  LaneTopology,
  LaneTopologyState,
)


SAMPLE_X_M = 10.0
NEAR_X_M = 5.0
FAR_X_M = 40.0
DOUBLE_LINE_MAX_WIDTH_M = 0.35
MIN_LANE_WIDTH_M = 2.2
MAX_LANE_WIDTH_M = 5.0
MERGE_WIDTH_M = 0.9


def canonical_points(points: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
  by_x: dict[float, list[float]] = {}
  for x, y in points:
    by_x.setdefault(float(x), []).append(float(y))
  return tuple((x, sum(ys) / len(ys)) for x, ys in sorted(by_x.items()))


def interpolate_y(points: tuple[tuple[float, float], ...], x_m: float) -> float | None:
  pts = canonical_points(points)
  if not pts or x_m < pts[0][0] or x_m > pts[-1][0]:
    return None
  for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
    if x0 <= x_m <= x1:
      if x1 == x0:
        return (y0 + y1) / 2.0
      ratio = (x_m - x0) / (x1 - x0)
      return y0 + ratio * (y1 - y0)
  return pts[-1][1] if x_m == pts[-1][0] else None


def _combine_marking_type(left: LaneMarkingType, right: LaneMarkingType) -> LaneMarkingType:
  types = {left, right}
  if types == {LaneMarkingType.solid}:
    return LaneMarkingType.doubleSolid
  if types == {LaneMarkingType.dashed}:
    return LaneMarkingType.doubleDashed
  if types == {LaneMarkingType.solid, LaneMarkingType.dashed}:
    return LaneMarkingType.solidDashed
  return left if left == right else LaneMarkingType.unknown


def _merge_points(primary: LaneBoundary, secondary: LaneBoundary) -> tuple[tuple[float, float], ...]:
  merged: list[tuple[float, float]] = []
  for x, y in canonical_points(primary.points):
    other_y = interpolate_y(secondary.points, x)
    merged.append((x, y if other_y is None else (y + other_y) / 2.0))
  return tuple(merged)


def merge_double_markings(boundaries: Iterable[LaneBoundary], sample_x_m: float = SAMPLE_X_M) -> tuple[LaneBoundary, ...]:
  visible = [replace(boundary, points=canonical_points(boundary.points)) for boundary in boundaries if boundary.visible]
  visible.sort(key=lambda boundary: interpolate_y(boundary.points, sample_x_m) or 0.0, reverse=True)
  merged: list[LaneBoundary] = []
  index = 0
  while index < len(visible):
    current = visible[index]
    if index + 1 < len(visible):
      nxt = visible[index + 1]
      current_y = interpolate_y(current.points, sample_x_m)
      next_y = interpolate_y(nxt.points, sample_x_m)
      if current_y is not None and next_y is not None and abs(current_y - next_y) <= DOUBLE_LINE_MAX_WIDTH_M:
        primary, secondary = (current, nxt) if current.confidence >= nxt.confidence else (nxt, current)
        merged.append(LaneBoundary(
          track_id=primary.track_id,
          points=_merge_points(primary, secondary),
          marking_type=_combine_marking_type(current.marking_type, nxt.marking_type),
          confidence=min(current.confidence, nxt.confidence),
          visible=True,
          left_component_marking=current.marking_type,
          right_component_marking=nxt.marking_type,
          left_component_source_id=current.left_component_source_id,
          right_component_source_id=nxt.right_component_source_id,
        ))
        index += 2
        continue
    merged.append(current)
    index += 1
  merged.sort(key=lambda boundary: interpolate_y(boundary.points, sample_x_m) or 0.0, reverse=True)
  return tuple(merged)


def observations_to_boundaries(observations: Iterable[LaneBoundaryObservation]) -> tuple[LaneBoundary, ...]:
  return tuple(LaneBoundary(
    track_id=observation.source_id,
    points=canonical_points(observation.points),
    marking_type=observation.marking_type,
    confidence=observation.confidence,
    visible=observation.visible,
    left_component_marking=observation.marking_type,
    right_component_marking=observation.marking_type,
    left_component_source_id=observation.source_id,
    right_component_source_id=observation.source_id,
  ) for observation in observations)


def _lane_spaces(boundaries: tuple[LaneBoundary, ...], sample_x_m: float) -> tuple[LaneSpace, ...]:
  spaces: list[LaneSpace] = []
  for left, right in zip(boundaries, boundaries[1:], strict=False):
    left_y, right_y = interpolate_y(left.points, sample_x_m), interpolate_y(right.points, sample_x_m)
    if left_y is None or right_y is None:
      continue
    width = left_y - right_y
    if MIN_LANE_WIDTH_M <= width <= MAX_LANE_WIDTH_M:
      spaces.append(LaneSpace(left.track_id, right.track_id, width, min(left.confidence, right.confidence)))
  return tuple(spaces)


def _topology_state(boundaries: tuple[LaneBoundary, ...]) -> LaneTopologyState:
  for left, right in zip(boundaries, boundaries[1:], strict=False):
    left_near, right_near = interpolate_y(left.points, NEAR_X_M), interpolate_y(right.points, NEAR_X_M)
    left_far, right_far = interpolate_y(left.points, FAR_X_M), interpolate_y(right.points, FAR_X_M)
    if None in (left_near, right_near, left_far, right_far):
      continue
    near_width = float(left_near) - float(right_near)
    far_width = float(left_far) - float(right_far)
    center_y = (float(left_near) + float(right_near)) / 2.0
    if near_width >= MIN_LANE_WIDTH_M and far_width <= MERGE_WIDTH_M:
      return LaneTopologyState.mergingLeft if center_y > 0 else LaneTopologyState.mergingRight
    if near_width <= MERGE_WIDTH_M and far_width >= MIN_LANE_WIDTH_M:
      return LaneTopologyState.splittingLeft if center_y > 0 else LaneTopologyState.splittingRight
  return LaneTopologyState.normal


def analyze_lane_topology(observations: Iterable[LaneBoundaryObservation] | Iterable[LaneBoundary], *, frame_id: int,
                          timestamp_ns: int, model_latency_ms: float = 0.0,
                          sample_x_m: float = SAMPLE_X_M) -> LaneTopology:
  items = tuple(observations)
  if not items:
    return LaneTopology.empty(frame_id, timestamp_ns)
  boundaries = (observations_to_boundaries(items) if isinstance(items[0], LaneBoundaryObservation) else tuple(items))  # type: ignore[arg-type]
  boundaries = merge_double_markings(boundaries, sample_x_m)
  spaces = _lane_spaces(boundaries, sample_x_m)

  y_by_track = {boundary.track_id: interpolate_y(boundary.points, sample_x_m) for boundary in boundaries}
  ego_space_index = next((index for index, space in enumerate(spaces)
                          if (y_by_track[space.left_track_id] or 0.0) > 0.0 > (y_by_track[space.right_track_id] or 0.0)), -1)
  state = _topology_state(boundaries)
  if ego_space_index < 0:
    state = LaneTopologyState.ambiguous

  visible_markings = sum(boundary.marking_type.physical_marking_count for boundary in boundaries if boundary.visible)
  confidence = (sum(space.confidence for space in spaces) / len(spaces)) if spaces else 0.0
  return LaneTopology(
    frame_id=frame_id,
    timestamp_ns=timestamp_ns,
    boundaries=boundaries,
    spaces=spaces,
    marking_count_visible=visible_markings,
    boundary_count_visible=len(boundaries),
    visible_lane_count=len(spaces),
    ego_lane_index_from_left=ego_space_index,
    ego_lane_index_from_right=(len(spaces) - 1 - ego_space_index) if ego_space_index >= 0 else -1,
    lanes_left_of_ego=ego_space_index if ego_space_index >= 0 else 0,
    lanes_right_of_ego=(len(spaces) - 1 - ego_space_index) if ego_space_index >= 0 else 0,
    state=state,
    confidence=confidence,
    model_latency_ms=model_latency_ms,
  )
