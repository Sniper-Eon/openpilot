from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import math

import numpy as np

from openpilot.sunnypilot.lane_topology.types import LaneMarkingType


REFERENCE_IMAGE_WIDTH = 526.0
MIN_ADAPTIVE_CONTRAST = 6.0
ADAPTIVE_PEAK_RATIO = 0.55
MIN_COHERENT_SAMPLES = 6
MAX_BLURRED_PROFILE_ROUGHNESS = 0.45
PARTIAL_DASHED_CONFIDENCE = 0.45


def marking_sampling_parameters(image_width: int) -> tuple[int, int, int]:
  """Scale pixel-space strip geometry with camera resolution."""
  if image_width <= 0:
    raise ValueError("image width must be positive")
  scale = max(1.0, image_width / REFERENCE_IMAGE_WIDTH)
  return (
    max(2, int(round(2 * scale))),
    max(10, int(round(10 * scale))),
    max(4, int(round(4 * scale))),
  )


@dataclass(frozen=True)
class MetricLaneSample:
  distance_m: float
  u: float
  v: float


@dataclass(frozen=True)
class MetricMarkingEvidence:
  marking_type: LaneMarkingType
  confidence: float
  sample_count: int
  lit_count: int
  coverage: float
  transitions: int
  lit_runs: int
  max_internal_dark_gap_m: float
  median_lit_run_m: float
  complete_lit_runs: int
  internal_dark_runs: int
  run_regularity: float

  @classmethod
  def unknown(cls, sample_count: int = 0) -> MetricMarkingEvidence:
    return cls(LaneMarkingType.unknown, 0.0, sample_count, 0, 0.0, 0, 0, 0.0, 0.0, 0, 0, 0.0)


def project_model_lane_metric_samples(lane_line: object, camera_from_calib: np.ndarray,
                                      image_width: int, image_height: int, *,
                                      min_distance_m: float = 8.0, max_distance_m: float = 35.0,
                                      distance_step_m: float = 1.0,
                                      image_margin_px: float = 20.0) -> tuple[MetricLaneSample, ...]:
  """Interpolate a model lane uniformly in metres, then project to the image."""

  if distance_step_m <= 0.0 or min_distance_m >= max_distance_m:
    raise ValueError("invalid metric lane sampling range")
  matrix = np.asarray(camera_from_calib, dtype=np.float64)
  if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
    raise ValueError("camera_from_calib must be a finite 3x3 matrix")
  xs = np.asarray(lane_line.x, dtype=np.float64)  # type: ignore[attr-defined]
  ys = np.asarray(lane_line.y, dtype=np.float64)  # type: ignore[attr-defined]
  zs = np.asarray(lane_line.z, dtype=np.float64)  # type: ignore[attr-defined]
  valid = np.isfinite(xs) & np.isfinite(ys) & np.isfinite(zs)
  xs, ys, zs = xs[valid], ys[valid], zs[valid]
  if len(xs) < 2:
    return ()
  order = np.argsort(xs)
  xs, ys, zs = xs[order], ys[order], zs[order]
  unique_x, unique_indices = np.unique(xs, return_index=True)
  ys, zs = ys[unique_indices], zs[unique_indices]
  start, end = max(min_distance_m, float(unique_x[0])), min(max_distance_m, float(unique_x[-1]))
  if end <= start:
    return ()
  sample_x = np.arange(start, end + distance_step_m * 0.5, distance_step_m)
  sample_y = np.interp(sample_x, unique_x, ys)
  sample_z = np.interp(sample_x, unique_x, zs)
  projected = matrix @ np.stack((sample_x, sample_y, sample_z))
  in_front = projected[2] > 1e-3
  pixels = projected[:2, in_front] / projected[2, in_front]
  distances = sample_x[in_front]
  inside = ((pixels[0] >= image_margin_px) & (pixels[0] < image_width - image_margin_px) &
            (pixels[1] >= image_margin_px) & (pixels[1] < image_height - image_margin_px))
  return tuple(MetricLaneSample(float(x), float(u), float(v))
               for x, u, v in zip(distances[inside], pixels[0, inside], pixels[1, inside], strict=True))


def _clean_binary_sequence(values: list[bool]) -> list[bool]:
  cleaned = values[:]
  for index in range(1, len(values) - 1):
    # Remove an isolated bright sample, but retain a one-metre dark gap. On
    # 526x330 input that gap can be a compressed dashed-line interval.
    if values[index] and not values[index - 1] and not values[index + 1]:
      cleaned[index] = False
  return cleaned


def _runs(values: list[bool], step_m: float) -> list[tuple[bool, float]]:
  if not values:
    return []
  runs: list[tuple[bool, float]] = []
  current, count = values[0], 1
  for value in values[1:]:
    if value == current:
      count += 1
    else:
      runs.append((current, count * step_m))
      current, count = value, 1
  runs.append((current, count * step_m))
  return runs


def _strip_means(luminance: np.ndarray, uv: np.ndarray, normal: np.ndarray, tangent_unit: np.ndarray,
                 offsets: np.ndarray, center_radius: int) -> np.ndarray:
  """Vectorized lane-tangent strip means at offsets along each lane normal."""

  centers = uv[:, None, :] + normal[:, None, :] * offsets[None, :, None]
  along = np.arange(-center_radius, center_radius + 1, dtype=np.float64)
  points = centers[:, :, None, :] + tangent_unit[:, None, None, :] * along[None, None, :, None]
  u_indices = np.rint(points[:, :, :, 0]).astype(np.int32)
  v_indices = np.rint(points[:, :, :, 1]).astype(np.int32)
  return luminance[v_indices, u_indices].mean(axis=-1)


def _offsets_are_coherent(distances: np.ndarray, offsets: np.ndarray, presence: np.ndarray,
                          search_radius: int) -> bool:
  selected_distances = distances[presence]
  selected_offsets = offsets[presence]
  if len(selected_offsets) < MIN_COHERENT_SAMPLES:
    return False
  trend = np.polyval(np.polyfit(selected_distances, selected_offsets, 1), selected_distances)
  residual_limit_px = max(1.0, search_radius * 0.25)
  return float(np.percentile(np.abs(selected_offsets - trend), 90)) <= residual_limit_px


def _profiles_are_smooth(levels: np.ndarray, presence: np.ndarray) -> bool:
  if np.count_nonzero(presence) < MIN_COHERENT_SAMPLES:
    return False
  span = np.ptp(levels, axis=1)
  roughness = np.mean(np.abs(np.diff(levels, n=2, axis=1)), axis=1)
  normalized = roughness / np.maximum(span, 1.0)
  return float(np.median(normalized[presence])) <= MAX_BLURRED_PROFILE_ROUGHNESS


def _recover_partial_dashed(evidence: MetricMarkingEvidence) -> MetricMarkingEvidence:
  partial = bool(
    0.12 <= evidence.coverage <= 0.82
    and evidence.lit_runs >= 2
    and evidence.complete_lit_runs >= 1
    and evidence.internal_dark_runs >= 1
    and evidence.max_internal_dark_gap_m >= 1.0
    and 0.5 <= evidence.median_lit_run_m <= 10.0
    and evidence.transitions >= 3
  )
  return replace(
    evidence, marking_type=LaneMarkingType.dashed, confidence=PARTIAL_DASHED_CONFIDENCE,
  ) if partial else evidence


def classify_metric_presence(distances_m: np.ndarray, presence: np.ndarray) -> MetricMarkingEvidence:
  distances = np.asarray(distances_m, dtype=np.float64)
  flags = np.asarray(presence, dtype=bool)
  if distances.ndim != 1 or flags.ndim != 1 or len(distances) != len(flags) or len(flags) < 12:
    return MetricMarkingEvidence.unknown(len(flags))
  steps = np.diff(distances)
  step_m = float(np.median(steps)) if len(steps) else 0.0
  if not math.isfinite(step_m) or step_m <= 0.0 or np.any(steps > step_m * 1.8):
    return MetricMarkingEvidence.unknown(len(flags))

  cleaned = _clean_binary_sequence(flags.tolist())
  run_values = _runs(cleaned, step_m)
  lit_lengths = [length for lit, length in run_values if lit]
  complete_lit_lengths = [length for index, (lit, length) in enumerate(run_values)
                          if lit and 0 < index < len(run_values) - 1]
  internal_dark = [length for index, (lit, length) in enumerate(run_values)
                   if not lit and 0 < index < len(run_values) - 1]
  coverage = sum(cleaned) / len(cleaned)
  transitions = sum(current != previous for previous, current in zip(cleaned, cleaned[1:], strict=False))
  lit_runs = len(lit_lengths)
  max_dark_gap = max(internal_dark, default=0.0)
  median_lit = float(np.median(lit_lengths)) if lit_lengths else 0.0
  lit_cv = float(np.std(complete_lit_lengths) / max(np.mean(complete_lit_lengths), 1e-3)) if len(complete_lit_lengths) >= 2 else math.inf
  dark_cv = float(np.std(internal_dark) / max(np.mean(internal_dark), 1e-3)) if len(internal_dark) >= 2 else math.inf
  run_regularity = 1.0 / (1.0 + lit_cv + dark_cv) if math.isfinite(lit_cv + dark_cv) else 0.0

  # Repeated, regularly spaced short gaps must not be swallowed by the solid
  # coverage rule. A lone missing sample still does not establish dashed paint.
  repeated_short_gaps = bool(max_dark_gap <= 2.0 and lit_cv <= 0.35 and dark_cv <= 0.35)
  if (0.12 <= coverage <= (0.94 if repeated_short_gaps else 0.82) and
      lit_runs >= 3 and len(complete_lit_lengths) >= 2 and len(internal_dark) >= 2 and
      max_dark_gap >= 1.0 and 0.5 <= median_lit <= 10.0 and transitions >= 5 and
      lit_cv <= 0.80 and dark_cv <= 0.80):
    marking_type = LaneMarkingType.dashed
    confidence = min(1.0, 0.30 + 0.10 * min(lit_runs, 5) + 0.30 * run_regularity)
  elif coverage >= 0.72 and max_dark_gap <= 1.5:
    marking_type = LaneMarkingType.solid
    confidence = min(1.0, max(0.0, (coverage - 0.65) / 0.30))
  else:
    marking_type = LaneMarkingType.unknown
    confidence = 0.0
  return MetricMarkingEvidence(marking_type, confidence, len(cleaned), sum(cleaned), coverage,
                               transitions, lit_runs, max_dark_gap, median_lit,
                               len(complete_lit_lengths), len(internal_dark), run_regularity)


def measure_metric_marking(image: np.ndarray, samples: tuple[MetricLaneSample, ...], *,
                           center_radius: int = 3, side_offset: int = 10,
                           search_radius: int = 4, contrast_threshold: float = 14.0,
                           adaptive: bool = True, partial_dashed: bool = True) -> MetricMarkingEvidence:
  source = np.asarray(image)
  if source.dtype != np.uint8 or source.ndim not in (2, 3) or (source.ndim == 3 and source.shape[2] != 3):
    raise ValueError("metric marking requires HxW luma or HxWx3 uint8 image")
  if len(samples) < 12:
    return MetricMarkingEvidence.unknown(len(samples))
  luminance = source if source.ndim == 2 else source.max(axis=2)
  height, width = luminance.shape
  distances = np.array([sample.distance_m for sample in samples], dtype=np.float64)
  uv = np.array([(sample.u, sample.v) for sample in samples], dtype=np.float64)
  tangent = np.empty_like(uv)
  tangent[1:-1] = uv[2:] - uv[:-2]
  tangent[0], tangent[-1] = uv[1] - uv[0], uv[-1] - uv[-2]
  norms = np.linalg.norm(tangent, axis=1)
  span = side_offset + center_radius + search_radius
  valid = ((norms >= 1e-6) & (uv[:, 0] >= span) & (uv[:, 0] < width - span) &
           (uv[:, 1] >= span) & (uv[:, 1] < height - span))
  if np.count_nonzero(valid) < 12:
    return MetricMarkingEvidence.unknown(int(np.count_nonzero(valid)))
  distances, uv, tangent, norms = distances[valid], uv[valid], tangent[valid], norms[valid]
  tangent_unit = tangent / norms[:, None]
  normal = np.stack((-tangent_unit[:, 1], tangent_unit[:, 0]), axis=1)
  center_offsets = np.arange(-search_radius, search_radius + 1, dtype=np.float64)
  center_levels = _strip_means(luminance, uv, normal, tangent_unit, center_offsets, center_radius)
  best_offsets = center_offsets[np.argmax(center_levels, axis=1)]
  center_level = center_levels.max(axis=1)
  side_levels = _strip_means(luminance, uv, normal, tangent_unit,
                             np.array((-side_offset, side_offset)), center_radius)
  contrast = center_level - side_levels.mean(axis=1)

  def structure_valid(evidence: MetricMarkingEvidence, presence: np.ndarray) -> bool:
    coherent = (_offsets_are_coherent(distances, best_offsets, presence, search_radius)
                or _profiles_are_smooth(center_levels, presence))
    if not coherent:
      return False
    if evidence.marking_type == LaneMarkingType.dashed and evidence.max_internal_dark_gap_m <= 2.0:
      # A short dark region across the paint AND both adjacent road strips is
      # compatible with a shadow, not independent evidence of a paint gap.
      lit_indices = np.flatnonzero(presence)
      internal_dark = ~presence & (np.arange(len(presence)) > lit_indices[0]) & (np.arange(len(presence)) < lit_indices[-1])
      if np.any(internal_dark):
        road_lit = float(np.median(side_levels[presence]))
        road_dark = float(np.median(side_levels[internal_dark]))
        if road_lit - road_dark > max(MIN_ADAPTIVE_CONTRAST, road_lit * 0.25):
          return False
    return True

  fixed_presence = contrast >= contrast_threshold
  fixed_evidence = classify_metric_presence(distances, fixed_presence)
  if fixed_evidence.marking_type == LaneMarkingType.solid:
    return fixed_evidence
  if fixed_evidence.marking_type == LaneMarkingType.dashed:
    if structure_valid(fixed_evidence, fixed_presence):
      return fixed_evidence
    fixed_evidence = MetricMarkingEvidence.unknown(len(distances))
  fixed_partial = _recover_partial_dashed(fixed_evidence) if partial_dashed else fixed_evidence
  fixed_structure_valid = bool(
    fixed_partial.marking_type != LaneMarkingType.unknown
    and structure_valid(fixed_partial, fixed_presence)
  )
  if not fixed_structure_valid:
    fixed_partial = MetricMarkingEvidence.unknown(len(distances))
  if not adaptive:
    return fixed_partial if fixed_partial.marking_type != LaneMarkingType.unknown else fixed_evidence
  peak_contrast = float(np.percentile(contrast, 90))
  adaptive_floor = min(MIN_ADAPTIVE_CONTRAST, contrast_threshold)
  adaptive_threshold = max(adaptive_floor, min(contrast_threshold, peak_contrast * ADAPTIVE_PEAK_RATIO))
  presence = contrast >= adaptive_threshold
  evidence = classify_metric_presence(distances, presence)
  if evidence.marking_type == LaneMarkingType.unknown and partial_dashed:
    evidence = _recover_partial_dashed(evidence)
  if evidence.marking_type == LaneMarkingType.unknown:
    return fixed_partial if fixed_partial.marking_type != LaneMarkingType.unknown else evidence
  if not structure_valid(evidence, presence):
    return fixed_partial if fixed_partial.marking_type != LaneMarkingType.unknown else MetricMarkingEvidence.unknown(len(distances))
  quality = min(1.0, max(0.25, peak_contrast / max(contrast_threshold, 1e-3)))
  return replace(evidence, confidence=evidence.confidence * quality)


class TemporalMarkingFilter:
  """Bounded, timestamped evidence; confidence changes settling time, not reachability."""

  def __init__(self, *, minimum_score: float = 3.0, dominance_ratio: float = 2.0, decay: float = 0.90):
    self.minimum_score = minimum_score
    self.dominance_ratio = dominance_ratio
    self.decay = decay
    self._history: list[deque[tuple[int, MetricMarkingEvidence]]] = [deque(maxlen=64) for _ in range(4)]
    self._last_timestamp_ns: list[int | None] = [None] * 4
    self._confirmed = [LaneMarkingType.unknown] * 4
    self.window_ns = 2_000_000_000
    self.max_evidence_gap_ns = 500_000_000

  def reset(self) -> None:
    for source_id, history in enumerate(self._history):
      history.clear()
      self._last_timestamp_ns[source_id] = None
      self._confirmed[source_id] = LaneMarkingType.unknown

  def update(self, source_id: int, evidence: MetricMarkingEvidence, *, timestamp_ns: int | None = None) -> LaneMarkingType:
    history = self._history[source_id]
    previous_ns = self._last_timestamp_ns[source_id]
    # Compatibility for isolated callers without a camera clock: one sample at
    # the production classifier's 100 ms period. Live/replay callers pass EOF.
    now_ns = int(timestamp_ns) if timestamp_ns is not None else (previous_ns or 0) + 100_000_000
    if previous_ns is not None:
      if now_ns == previous_ns:
        return self._confirmed[source_id]
      if now_ns < previous_ns or now_ns - previous_ns > self.max_evidence_gap_ns:
        history.clear()
        self._confirmed[source_id] = LaneMarkingType.unknown
    self._last_timestamp_ns[source_id] = now_ns
    while history and now_ns - history[0][0] > self.window_ns:
      history.popleft()

    partial_dashed = bool(
      evidence.marking_type == LaneMarkingType.dashed
      and (evidence.lit_runs < 3 or evidence.complete_lit_runs < 2
           or evidence.internal_dark_runs < 2 or evidence.transitions < 5)
    )
    recent_solid = any(now_ns - ts <= self.max_evidence_gap_ns and item.marking_type == LaneMarkingType.solid
                       for ts, item in history)
    if partial_dashed and recent_solid:
      evidence = MetricMarkingEvidence.unknown(evidence.sample_count)
    history.append((now_ns, evidence))
    scores = {LaneMarkingType.solid: 0.0, LaneMarkingType.dashed: 0.0}
    support = dict.fromkeys(scores, 0.0)
    first_ns: dict[LaneMarkingType, int] = {}
    last_ns: dict[LaneMarkingType, int] = {}
    total_support = 0.0
    for ts, item in history:
      weight = self.decay ** ((now_ns - ts) / 100_000_000)
      total_support += weight
      if item.marking_type in scores and math.isfinite(item.confidence) and 0.0 < item.confidence <= 1.0:
        scores[item.marking_type] += weight * item.confidence
        support[item.marking_type] += weight
        first_ns.setdefault(item.marking_type, ts)
        last_ns[item.marking_type] = ts
    winner = max(scores, key=scores.get)
    loser = LaneMarkingType.dashed if winner == LaneMarkingType.solid else LaneMarkingType.solid
    mean_confidence = scores[winner] / max(support[winner], 1e-12)
    settling_seconds = self.minimum_score * 0.1 + 0.7 * (1.0 - mean_confidence) + (0.2 if partial_dashed else 0.0)
    duration_ns = last_ns.get(winner, now_ns) - first_ns.get(winner, now_ns)
    fresh = winner in last_ns and now_ns - last_ns[winner] <= self.max_evidence_gap_ns
    if (fresh and duration_ns >= settling_seconds * 1e9 and support[winner] >= self.minimum_score
        and support[winner] >= total_support * self.dominance_ratio / (1.0 + self.dominance_ratio)
        and scores[winner] >= max(1e-12, scores[loser]) * self.dominance_ratio):
      self._confirmed[source_id] = winner
      return winner
    self._confirmed[source_id] = LaneMarkingType.unknown
    return LaneMarkingType.unknown
