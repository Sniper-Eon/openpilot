from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np

from openpilot.sunnypilot.lane_topology.metric_marking import classify_metric_presence, \
                                                                  measure_metric_marking, \
                                                                  MetricLaneSample, \
                                                                  marking_sampling_parameters, \
                                                                  project_model_lane_metric_samples, \
                                                                  TemporalMarkingFilter
from openpilot.sunnypilot.lane_topology.types import LaneMarkingType


def synthetic_marking(kind: LaneMarkingType, *, contrast: int, blur_sigma: float) -> tuple[np.ndarray, tuple[MetricLaneSample, ...]]:
  image = np.full((120, 180), 50, dtype=np.uint8)
  samples = tuple(MetricLaneSample(float(distance), 30 + (distance - 8) * 4, 60.0)
                  for distance in np.arange(8.0, 36.0, 1.0))
  if kind == LaneMarkingType.solid:
    image[57:64, :] = 50 + contrast
  elif kind == LaneMarkingType.dashed:
    for column in range(image.shape[1]):
      distance = 8.0 + (column - 30) / 4.0
      if distance % 9.0 < 3.0:
        image[57:64, column] = 50 + contrast
  else:
    raise ValueError("synthetic fixture supports only solid and dashed")
  if blur_sigma > 0.0:
    image = cv2.GaussianBlur(image, (0, 0), sigmaX=blur_sigma, sigmaY=blur_sigma)
  return image, samples


def test_metric_presence_classifies_solid_and_physical_dash_gaps():
  distances = np.arange(5.0, 35.0, 0.5)
  solid = classify_metric_presence(distances, np.ones_like(distances, dtype=bool))
  assert solid.marking_type == LaneMarkingType.solid

  dashed_pattern = ((distances % 9.0) < 3.0)
  dashed = classify_metric_presence(distances, dashed_pattern)
  assert dashed.marking_type == LaneMarkingType.dashed
  assert dashed.max_internal_dark_gap_m >= 5.0
  assert dashed.complete_lit_runs >= 2
  assert dashed.internal_dark_runs >= 2
  assert dashed.run_regularity > 0.5


def test_repeated_one_metre_gaps_are_not_swallowed_by_high_solid_coverage():
  distances = np.arange(28.0)
  presence = np.ones(28, dtype=bool)
  presence[[7, 15, 23]] = False
  evidence = classify_metric_presence(distances, presence)

  assert evidence.coverage > 0.82
  assert evidence.marking_type == LaneMarkingType.dashed
  presence[:] = True
  presence[15] = False
  assert classify_metric_presence(distances, presence).marking_type == LaneMarkingType.solid


def test_short_gap_classification_rejects_shadow_across_paint_and_adjacent_road():
  samples = tuple(MetricLaneSample(float(distance), 30.0 + distance * 4.0, 60.0) for distance in range(28))
  paint_gap = np.full((120, 180), 40, dtype=np.uint8)
  paint_gap[59:62, :] = 100
  shadow = paint_gap.copy()
  for distance in (7, 15, 23):
    column = int(samples[distance].u)
    paint_gap[59:62, column - 1:column + 2] = 40
    shadow[:, column - 1:column + 2] = 20
    shadow[59:62, column - 1:column + 2] = 25

  assert measure_metric_marking(paint_gap, samples, center_radius=1).marking_type == LaneMarkingType.dashed
  assert measure_metric_marking(shadow, samples, center_radius=1).marking_type == LaneMarkingType.unknown


def test_metric_presence_fails_closed_on_sparse_or_irregular_samples():
  assert classify_metric_presence(np.arange(5.0), np.ones(5, dtype=bool)).marking_type == LaneMarkingType.unknown
  distances = np.array([float(index) for index in range(12)])
  distances[8:] += 10.0
  assert classify_metric_presence(distances, np.ones(12, dtype=bool)).marking_type == LaneMarkingType.unknown


def test_metric_marking_recovers_moderately_blurred_low_contrast_lines():
  for expected in (LaneMarkingType.solid, LaneMarkingType.dashed):
    image, samples = synthetic_marking(expected, contrast=20, blur_sigma=4.0)
    assert measure_metric_marking(image, samples, adaptive=False).marking_type == LaneMarkingType.unknown
    evidence = measure_metric_marking(image, samples)
    assert evidence.marking_type == expected
    assert 0.0 < evidence.confidence < 1.0


def test_metric_marking_uses_repeated_partial_dashes_as_low_confidence_evidence():
  image, samples = synthetic_marking(LaneMarkingType.dashed, contrast=40, blur_sigma=0.0)
  low_resolution_window = tuple(sample for sample in samples if 8.0 <= sample.distance_m <= 24.0)

  strict = measure_metric_marking(image, low_resolution_window, adaptive=False, partial_dashed=False)
  recovered = measure_metric_marking(image, low_resolution_window, adaptive=False)

  assert strict.marking_type == LaneMarkingType.unknown
  assert recovered.marking_type == LaneMarkingType.dashed
  assert 0.0 < recovered.confidence <= 0.45


def test_partial_dashes_accept_a_two_metre_compression_gap():
  image = np.full((120, 180), 50, dtype=np.uint8)
  samples = tuple(MetricLaneSample(float(distance), 30 + (distance - 8) * 4, 60.0)
                  for distance in np.arange(8.0, 25.0, 1.0))
  for start_distance, end_distance in ((10.0, 15.0), (17.0, 22.0)):
    start = int(30 + (start_distance - 8) * 4)
    end = int(30 + (end_distance - 8) * 4)
    image[57:64, start:end] = 90

  evidence = measure_metric_marking(image, samples, adaptive=False)

  assert evidence.marking_type == LaneMarkingType.dashed
  assert evidence.confidence <= 0.45


def test_metric_marking_blur_never_flips_solid_and_dashed():
  for expected in (LaneMarkingType.solid, LaneMarkingType.dashed):
    for contrast in (15, 20, 30, 40):
      for blur_sigma in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0):
        image, samples = synthetic_marking(expected, contrast=contrast, blur_sigma=blur_sigma)
        actual = measure_metric_marking(image, samples).marking_type
        assert actual in (expected, LaneMarkingType.unknown)


def test_metric_marking_rejects_unstructured_high_contrast_texture():
  samples = tuple(MetricLaneSample(float(distance), 30 + (distance - 8) * 4, 60.0)
                  for distance in np.arange(8.0, 36.0, 1.0))
  temporal = TemporalMarkingFilter()
  for seed in range(100):
    noise = np.random.default_rng(seed).normal(0.0, 10.0, (120, 180))
    image = np.clip(80.0 + noise, 0.0, 255.0).astype(np.uint8)
    evidence = measure_metric_marking(image, samples)
    assert temporal.update(1, evidence) == LaneMarkingType.unknown


def test_metric_projection_interpolates_uniform_forward_distance():
  lane = SimpleNamespace(x=(0.0, 10.0, 20.0), y=(0.0, 0.0, 0.0), z=(1.0, 1.0, 1.0))
  samples = project_model_lane_metric_samples(lane, np.eye(3), 100, 100,
                                              min_distance_m=5.0, max_distance_m=15.0,
                                              distance_step_m=0.5, image_margin_px=0.0)
  assert [sample.distance_m for sample in samples] == list(np.arange(5.0, 15.5, 0.5))


def test_marking_sampling_geometry_scales_linearly_with_camera_resolution():
  assert marking_sampling_parameters(526) == (2, 10, 4)
  center, side, search = marking_sampling_parameters(1928)
  assert (center, side, search) == (7, 37, 15)


def test_temporal_filter_requires_repeated_dominant_evidence():
  distances = np.arange(5.0, 35.0, 0.5)
  evidence = classify_metric_presence(distances, (distances % 9.0) < 3.0)
  temporal = TemporalMarkingFilter()
  assert temporal.update(1, evidence) == LaneMarkingType.unknown
  result = LaneMarkingType.unknown
  for _ in range(5):
    result = temporal.update(1, evidence)
  assert result == LaneMarkingType.dashed


def test_partial_dashes_can_reacquire_after_recent_solid_evidence_expires():
  temporal = TemporalMarkingFilter()
  distances = np.arange(12.0)
  solid = classify_metric_presence(distances, np.ones(12, dtype=bool))
  image, samples = synthetic_marking(LaneMarkingType.dashed, contrast=40, blur_sigma=0.0)
  partial_dashed = measure_metric_marking(
    image, tuple(sample for sample in samples if 8.0 <= sample.distance_m <= 24.0), adaptive=False,
  )

  for _ in range(6):
    temporal.update(1, solid)
  assert all(temporal.update(1, partial_dashed) != LaneMarkingType.dashed for _ in range(4))

  result = LaneMarkingType.unknown
  for _ in range(30):
    result = temporal.update(1, partial_dashed)
  assert result == LaneMarkingType.dashed


def test_repeated_low_confidence_evidence_can_confirm_at_four_and_ten_hz():
  image, samples = synthetic_marking(LaneMarkingType.dashed, contrast=40, blur_sigma=0.0)
  evidence = measure_metric_marking(image, tuple(sample for sample in samples if sample.distance_m <= 24.0))
  weak = replace(evidence, confidence=0.2)
  for period_ns in (100_000_000, 250_000_000):
    temporal = TemporalMarkingFilter()
    result = LaneMarkingType.unknown
    for timestamp_ns in range(period_ns, 2_000_000_001, period_ns):
      result = temporal.update(1, weak, timestamp_ns=timestamp_ns)
    assert result == LaneMarkingType.dashed


def test_timestamp_gap_and_unknown_frames_expire_prior_confirmation():
  temporal = TemporalMarkingFilter()
  solid = classify_metric_presence(np.arange(28.0), np.ones(28, dtype=bool))
  for timestamp_ns in range(100_000_000, 900_000_000, 100_000_000):
    result = temporal.update(1, solid, timestamp_ns=timestamp_ns)
  assert result == LaneMarkingType.solid
  assert temporal.update(1, solid, timestamp_ns=2_000_000_000) == LaneMarkingType.unknown
  for timestamp_ns in range(2_100_000_000, 2_900_000_000, 100_000_000):
    result = temporal.update(1, solid, timestamp_ns=timestamp_ns)
  assert result == LaneMarkingType.solid
  for timestamp_ns in range(2_900_000_000, 3_600_000_000, 100_000_000):
    result = temporal.update(1, replace(solid, marking_type=LaneMarkingType.unknown, confidence=0.0), timestamp_ns=timestamp_ns)
  assert result == LaneMarkingType.unknown


def test_duplicate_timestamps_do_not_create_independent_evidence():
  temporal = TemporalMarkingFilter()
  solid = classify_metric_presence(np.arange(28.0), np.ones(28, dtype=bool))
  assert all(temporal.update(1, solid, timestamp_ns=100_000_000) == LaneMarkingType.unknown for _ in range(20))
