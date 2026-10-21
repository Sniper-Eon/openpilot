from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from dataclasses import replace
import math
from typing import Protocol

from openpilot.sunnypilot.lane_topology.adapter import LaneTopologyFrame
from openpilot.sunnypilot.lane_topology.geometry import canonical_points, interpolate_y
from openpilot.sunnypilot.lane_topology.types import LaneBoundaryObservation, LaneMarkingType


MarkingClassifier = Callable[[int, object], LaneMarkingType]

# 2026-10-17 highway replay (7,007 ego frames): 0.8/1.5 raised the left anchor
# from 8.7% to 53.7% and both-edge frames from 0.9% to 3.6% without labelling
# edges that sit inside the lane.  1.0/1.5 added nothing over 0.8/1.5.
ROAD_EDGE_MAX_STD = 0.8
ROAD_EDGE_MAX_DELTA_M = 1.5
ROAD_EDGE_SAMPLE_X_M = 15.0


class LaneLineLike(Protocol):
  x: Iterable[float]
  y: Iterable[float]


class ModelV2Like(Protocol):
  laneLines: Iterable[LaneLineLike]
  laneLineProbs: Iterable[float]


def find_ego_source_ids(observations: Iterable[LaneBoundaryObservation], *, sample_x_m: float = 10.0) -> tuple[int, int] | None:
  """Return the model source IDs immediately left and right of vehicle y=0."""

  positioned = []
  for observation in observations:
    y = interpolate_y(canonical_points(observation.points), sample_x_m)
    if y is not None:
      positioned.append((y, observation.source_id))
  positioned.sort(reverse=True)
  for (left_y, left_id), (right_y, right_id) in zip(positioned, positioned[1:], strict=False):
    if left_y > 0.0 > right_y:
      return left_id, right_id
  return None


def model_v2_to_observations(model_v2: ModelV2Like, *, confidence_threshold: float = 0.35,
                             marking_classifier: MarkingClassifier | None = None,
                             max_distance_m: float = 80.0,
                             visible_source_ids: Collection[int] | None = None) -> tuple[LaneBoundaryObservation, ...]:
  """Reuse modelV2's four lane lines without running another neural network.

  This adapter is deliberately duck-typed so it works with both Cap'n Proto
  readers and small replay fixtures. It does not mutate modelV2 and has no
  dependency on messaging, GPU, camera, planner, or control code.
  """

  lane_lines = tuple(model_v2.laneLines)
  probabilities = tuple(float(value) for value in model_v2.laneLineProbs)
  if len(lane_lines) != 4 or len(probabilities) != 4:
    raise ValueError("primary model lane topology requires exactly four lane lines and probabilities")
  if not 0.0 <= confidence_threshold <= 1.0:
    raise ValueError("confidence_threshold must be within [0, 1]")

  observations: list[LaneBoundaryObservation] = []
  for source_id, (lane_line, confidence) in enumerate(zip(lane_lines, probabilities, strict=True)):
    if ((visible_source_ids is not None and source_id not in visible_source_ids) or
        not math.isfinite(confidence) or confidence < confidence_threshold):
      continue
    xs = tuple(lane_line.x)
    ys = tuple(lane_line.y)
    if len(xs) != len(ys):
      raise ValueError(f"lane line {source_id} has mismatched x/y lengths")
    # modelV2 uses calibration/device convention (right-positive y); topology
    # intentionally exposes road convention (left-positive y).
    points = tuple((float(x), -float(y)) for x, y in zip(xs, ys, strict=True)
                   if math.isfinite(x) and math.isfinite(y) and 0.0 <= x <= max_distance_m)
    if len(points) < 2:
      continue
    marking_type = marking_classifier(source_id, lane_line) if marking_classifier is not None else LaneMarkingType.unknown
    observations.append(LaneBoundaryObservation(
      source_id=source_id,
      points=points,
      marking_type=marking_type,
      confidence=min(confidence, 1.0),
    ))
  return tuple(observations)


class PrimaryLaneVisibilityFilter:
  """Per-slot probability hysteresis for the primary model's four lines."""

  def __init__(self, *, enter_threshold: float = 0.5, exit_threshold: float = 0.20):
    if not 0.0 <= exit_threshold < enter_threshold <= 1.0:
      raise ValueError("lane visibility requires 0 <= exit < enter <= 1")
    self.enter_threshold = enter_threshold
    self.exit_threshold = exit_threshold
    self._visible = [False] * 4

  def reset(self) -> None:
    self._visible = [False] * 4

  def update(self, probabilities: Iterable[float]) -> frozenset[int]:
    values = tuple(float(value) for value in probabilities)
    if len(values) != 4:
      raise ValueError("lane visibility requires exactly four probabilities")
    for index, probability in enumerate(values):
      threshold = self.exit_threshold if self._visible[index] else self.enter_threshold
      self._visible[index] = math.isfinite(probability) and probability >= threshold
    return frozenset(index for index, visible in enumerate(self._visible) if visible)


class PrimaryModelLaneTopologyAdapter:
  """Shadow adapter for already-published modelV2 data; owns no GPU resources."""

  def __init__(self, *, enter_threshold: float = 0.5, exit_threshold: float = 0.20,
               marking_classifier: MarkingClassifier | None = None):
    self.visibility = PrimaryLaneVisibilityFilter(enter_threshold=enter_threshold, exit_threshold=exit_threshold)
    self.marking_classifier = marking_classifier

  def infer(self, frame: LaneTopologyFrame) -> tuple[LaneBoundaryObservation, ...]:
    visible = self.visibility.update(frame.payload.laneLineProbs)  # type: ignore[attr-defined]
    return model_v2_to_observations(frame.payload, confidence_threshold=0.0,  # type: ignore[arg-type]
                                    marking_classifier=self.marking_classifier, visible_source_ids=visible)

  def close(self) -> None:
    self.visibility.reset()


def _line_y_at(line, x_m: float) -> float | None:
  try:
    xs = tuple(float(value) for value in line.x)
    ys = tuple(float(value) for value in line.y)
  except (AttributeError, TypeError, ValueError):
    return None
  if len(xs) != len(ys) or len(xs) < 2:
    return None
  points = tuple((x, y) for x, y in zip(xs, ys, strict=True) if math.isfinite(x) and math.isfinite(y))
  if len(points) < 2:
    return None
  return interpolate_y(canonical_points(points), x_m)


def apply_model_road_edges(observations: Iterable[LaneBoundaryObservation], model_v2: object, *,
                           sample_x_m: float = ROAD_EDGE_SAMPLE_X_M,
                           max_std: float = ROAD_EDGE_MAX_STD,
                           max_delta_m: float = ROAD_EDGE_MAX_DELTA_M) -> tuple[LaneBoundaryObservation, ...]:
  """Label an outermost lane line as a road edge from modelV2's own edge.

  ``modelV2.roadEdges`` is an independent head trained for physical road
  boundaries.  It is only used when its std is low and it lands on the
  outermost visible lane line, so it cannot relabel an interior lane.  The
  image classifier never emits ``roadEdge``; this is the live source for the
  same-direction anchor.  Existing ``doubleSolid`` evidence is never
  overwritten.
  """
  items = tuple(observations)
  if not items:
    return items
  edges: list[float] = []
  for edge, std in zip(getattr(model_v2, "roadEdges", ()), getattr(model_v2, "roadEdgeStds", ()), strict=False):
    try:
      value = float(std)
    except (TypeError, ValueError):
      continue
    if not math.isfinite(value) or value > max_std:
      continue
    y = _line_y_at(edge, sample_x_m)
    if y is not None:
      # modelV2 uses right-positive y; lane topology uses left-positive y.
      edges.append(-y)
  if not edges:
    return items

  positioned: list[tuple[float, int]] = []
  for index, observation in enumerate(items):
    y = interpolate_y(canonical_points(observation.points), sample_x_m)
    if y is not None:
      positioned.append((y, index))
  if not positioned:
    return items
  left_y, left_index = max(positioned)
  right_y, right_index = min(positioned)

  marked: set[int] = set()
  for y in edges:
    # The edge must lie outside the outermost line, never inside the lane.
    if y > 0.0 and left_y <= y <= left_y + max_delta_m:
      marked.add(left_index)
    elif y < 0.0 and right_y - max_delta_m <= y <= right_y:
      marked.add(right_index)
  if not marked:
    return items
  rewritable = {LaneMarkingType.unknown, LaneMarkingType.solid, LaneMarkingType.dashed}
  return tuple(replace(observation, marking_type=LaneMarkingType.roadEdge)
               if index in marked and observation.marking_type in rewritable else observation
               for index, observation in enumerate(items))
