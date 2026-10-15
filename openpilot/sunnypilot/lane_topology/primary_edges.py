"""Geometry candidates from the device's real modelV2 schema, for evaluation.

Road edges do not identify the extent of the same-direction carriageway. Even
an integer-looking width can include a shoulder or opposing traffic. Candidates
here therefore never authorize absolute feedback or a lane change.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import median

from openpilot.sunnypilot.lane_topology.geometry import interpolate_y

SAMPLE_X = (5.0, 10.0, 20.0)
MAX_EDGE_STD_M = 0.35
MIN_LINE_PROB = 0.7
INTEGER_TOLERANCE = 0.15


@dataclass(frozen=True)
class PrimaryEdgeCandidate:
  reason: str
  candidate_index: int | None = None
  candidate_count: int | None = None
  lane_width_m: float | None = None
  left_edge_m: float | None = None
  right_edge_m: float | None = None
  absolute_confirmed: bool = False

  def to_dict(self) -> dict:
    return asdict(self)


def _points(line) -> tuple[tuple[float, float], ...]:
  xs, ys = tuple(line.x), tuple(line.y)
  if len(xs) != len(ys) or len(xs) < 2:
    raise ValueError('malformed curve')
  points = tuple((float(x), float(y)) for x, y in zip(xs, ys, strict=True))
  if any(not math.isfinite(x) or not math.isfinite(y) for x, y in points):
    raise ValueError('non-finite curve')
  if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
    raise ValueError('unordered curve')
  return points


def primary_edge_candidate(model) -> PrimaryEdgeCandidate:
  """Use right-positive device coordinates and actual ego lines (slots 1, 2).

  Count whole lane widths *outside the ego lane*, rather than dividing distance
  from the camera centre by an arbitrary constant. Require agreeing geometry at
  several longitudinal distances. This is a diagnostic candidate, not proof.
  """
  try:
    lines, edges = tuple(model.laneLines), tuple(model.roadEdges)
    probs = tuple(float(p) for p in model.laneLineProbs)
    stds = tuple(float(s) for s in model.roadEdgeStds)
    if len(lines) != 4 or len(edges) != 2 or len(probs) != 4 or len(stds) != 2:
      return PrimaryEdgeCandidate('missingGeometry')
    if any(not math.isfinite(s) or not 0 <= s <= MAX_EDGE_STD_M for s in stds):
      return PrimaryEdgeCandidate('uncertainRoadEdges')
    if any(not math.isfinite(p) or not MIN_LINE_PROB <= p <= 1 for p in probs[1:3]):
      return PrimaryEdgeCandidate('uncertainEgoLines')
    curves = tuple(_points(line) for line in (edges[0], lines[1], lines[2], edges[1]))
  except (AttributeError, TypeError, ValueError, OverflowError):
    return PrimaryEdgeCandidate('malformedGeometry')

  results = []
  for x in SAMPLE_X:
    values = tuple(interpolate_y(curve, x) for curve in curves)
    if any(y is None for y in values):
      return PrimaryEdgeCandidate('insufficientCurveRange')
    left_edge, ego_left, ego_right, right_edge = values
    if not left_edge <= ego_left < 0 < ego_right <= right_edge:
      return PrimaryEdgeCandidate('inconsistentEdgeOrder')
    width = ego_right - ego_left
    if not 2.5 <= width <= 4.5:
      return PrimaryEdgeCandidate('implausibleEgoWidth')
    extra_left = (ego_left - left_edge) / width
    extra_right = (right_edge - ego_right) / width
    left, right = round(extra_left), round(extra_right)
    if max(abs(extra_left - left), abs(extra_right - right)) > INTEGER_TOLERANCE:
      return PrimaryEdgeCandidate('nonIntegralRoadWidth')
    if not 0 <= left <= 11 or not 0 <= right <= 11 or left + right + 1 > 12:
      return PrimaryEdgeCandidate('laneRangeExceeded')
    results.append((left + 1, left + right + 1, width, -left_edge, right_edge))
  if len({r[:2] for r in results}) != 1:
    return PrimaryEdgeCandidate('longitudinalDisagreement')
  if max(r[2] for r in results) - min(r[2] for r in results) > 0.35:
    return PrimaryEdgeCandidate('changingLaneWidth')
  index, count = results[0][:2]
  return PrimaryEdgeCandidate(
    'carriagewayDirectionUnconfirmed', index, count,
    median(r[2] for r in results), median(r[3] for r in results), median(r[4] for r in results),
  )
