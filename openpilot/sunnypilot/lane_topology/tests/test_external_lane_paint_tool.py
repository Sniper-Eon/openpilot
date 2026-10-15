import ast
from pathlib import Path

import numpy as np
import pytest

from tools.inspect_external_lane_paint import MASK_PRESENT, SHIFT_PX, curve_features, inspect_curves

ROOT = Path(__file__).resolve().parents[4]
HEIGHT, WIDTH = 60, 120


def canvas(*, bright_x: int, dark_x: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
  """A light line on mid grey beside a dark band, with a lane mask on both."""
  gray = np.full((HEIGHT, WIDTH), 128, dtype=np.uint8)
  gray[:, bright_x] = 230
  gray[:, dark_x] = 40
  hsv = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
  hsv[:, bright_x, 1] = 10
  hsv[:, dark_x, 1] = 90
  lane_mask = np.zeros((HEIGHT, WIDTH), dtype=np.float64)
  lane_mask[:, bright_x] = 1.0
  lane_mask[:, dark_x] = 1.0
  return gray, hsv, lane_mask


def curve_at(x_normalised: float) -> list[list[float]]:
  return [[x_normalised, y / 10.0] for y in range(1, 6)]


def test_a_light_line_and_a_dark_band_are_separated_by_brightness_and_saturation():
  gray, hsv, lane_mask = canvas(bright_x=36, dark_x=84)
  rows = inspect_curves(gray=gray, hsv=hsv, lane_mask=lane_mask,
                        curves=[curve_at(0.3), curve_at(0.7)])

  paint, dark = rows[0], rows[1]
  assert paint['median_brightness'] == 230 and dark['median_brightness'] == 40
  assert paint['median_saturation'] == 10 and dark['median_saturation'] == 90
  # The within-frame rank is what a threshold-free rule would use.
  assert paint['brightness_rank'] == 0 and dark['brightness_rank'] == 1


def test_colour_is_sampled_on_the_native_frame_not_on_the_smaller_mask():
  # The whole point of a normalised curve: one point, two rasters. Using the mask
  # extent to index the native image reads the wrong pixels.
  gray = np.full((HEIGHT, WIDTH), 128, dtype=np.uint8)
  gray[:, 36] = 230
  hsv = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
  lane_mask = np.zeros((HEIGHT // 2, WIDTH // 2), dtype=np.float64)
  lane_mask[:, 18] = 1.0

  row = curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=curve_at(0.3))

  assert row['mask_coverage'] == 1.0
  assert row['median_brightness'] == 230


def test_the_features_do_not_claim_a_verdict():
  gray, hsv, lane_mask = canvas(bright_x=36, dark_x=84)
  row = curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=curve_at(0.3))

  assert set(row) == {'points', 'mask_coverage', 'mask_gaps', 'median_brightness',
                      'median_saturation', 'contrast_vs_shift'}
  assert 'marking_type' not in row and 'is_paint' not in row


def test_coverage_and_gaps_report_dashes_along_the_curve():
  gray, hsv, lane_mask = canvas(bright_x=36, dark_x=84)
  solid = curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=curve_at(0.3))
  assert solid['mask_coverage'] == 1.0 and solid['mask_gaps'] == 0

  lane_mask[:, 36] = 0.0
  lane_mask[::12, 36] = 1.0
  dashed = curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=curve_at(0.3))
  assert dashed['mask_coverage'] < 1.0 and dashed['mask_gaps'] >= 1


def test_the_lateral_contrast_follows_the_neighbourhood_not_the_exposure():
  gray, hsv, lane_mask = canvas(bright_x=36, dark_x=84)
  row = curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=curve_at(0.3))
  # 230 against 128 on both sides.
  assert row['contrast_vs_shift'] == pytest.approx(230 - 128)

  gray[:, :] = 10  # a much darker exposure, the same line
  gray[:, 36] = 120
  dim = curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=curve_at(0.3))
  assert dim['median_brightness'] < row['median_brightness']
  assert dim['contrast_vs_shift'] == pytest.approx(120 - 10)


def test_malformed_input_is_refused():
  gray, hsv, lane_mask = canvas(bright_x=36, dark_x=84)
  with pytest.raises(ValueError):
    curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=[[0.3, 0.1]])
  with pytest.raises(ValueError):
    curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=[[0.3, 0.1], [0.3]])
  # The mask lives on the observer canvas and may be a different size than the
  # native image, but it must still be a 2D image.
  assert curve_features(gray=gray, hsv=hsv, lane_mask=np.zeros((5, 5)),
                        points=curve_at(0.3))['points'] == 5
  with pytest.raises(ValueError):
    curve_features(gray=gray, hsv=hsv, lane_mask=np.zeros(5), points=curve_at(0.3))
  with pytest.raises(ValueError):
    curve_features(gray=gray, hsv=hsv, lane_mask=np.zeros((5, 5, 1)), points=curve_at(0.3))
  with pytest.raises(ValueError):
    curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=curve_at(0.3), shift_px=WIDTH)
  with pytest.raises(ValueError):
    inspect_curves(gray=gray, hsv=hsv, lane_mask=lane_mask, curves=[curve_at(0.3)] * 65)


def test_the_thresholds_the_tool_uses_are_stated_not_hidden():
  assert 0.0 < MASK_PRESENT < 1.0 and SHIFT_PX > 0


def test_the_tool_is_offline_and_reuses_the_observer_pipeline():
  source = (ROOT / 'tools/inspect_external_lane_paint.py').read_text()
  ast.parse(source)
  for forbidden in ('PubMaster', 'SubMaster', 'Params', 'sendcan', 'cereal', 'visionipc', 'VisionIpcClient'):
    assert forbidden not in source, forbidden
  # The masks must come from the shipped pipeline, not a second copy of it.
  assert 'infer_with_masks' in source
