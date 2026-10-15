import ast
from pathlib import Path

import numpy as np
import pytest

from openpilot.sunnypilot.lane_topology.ground_projection import (
  boundary_observation_from_image,
  ground_homography,
  image_to_vehicle,
  vehicle_to_image,
)
from openpilot.sunnypilot.lane_topology.types import LaneMarkingType

ROOT = Path(__file__).resolve().parents[4]

FOCAL = 300.0
PRINCIPAL_X, PRINCIPAL_Y = 320.0, 192.0
CAMERA_HEIGHT_M = 1.2


def camera_matrix() -> np.ndarray:
  """The shipped convention: intrinsics @ view_from_calib over camera-centred (x, y, z).

  ``x`` is forward, ``y`` left-positive and ``z`` up, so the road surface is the
  plane ``z = -camera_height``.
  """
  intrinsics = np.array(((FOCAL, 0.0, PRINCIPAL_X), (0.0, FOCAL, PRINCIPAL_Y), (0.0, 0.0, 1.0)))
  view_from_calib = np.array(((0.0, 1.0, 0.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0)))
  return intrinsics @ view_from_calib


def horizon_pixel() -> tuple[float, float]:
  return PRINCIPAL_X, PRINCIPAL_Y


def point_above_the_horizon() -> tuple[float, float]:
  """A pixel of a point floating above the road, so the ray never meets the plane."""
  projected = camera_matrix() @ np.array((10.0, 0.0, 2.0))
  return float(projected[0] / projected[2]), float(projected[1] / projected[2])


def test_the_module_is_projection_only_and_carries_no_vision_runtime():
  source = (ROOT / 'openpilot/sunnypilot/lane_topology/ground_projection.py').read_text()
  ast.parse(source)
  for forbidden in ('cv2', 'torch', 'visionipc', 'VisionBuf', 'messaging', 'Params'):
    assert forbidden not in source, forbidden


def test_the_homography_matches_the_forward_projection_the_repo_already_uses():
  matrix = camera_matrix()
  homography = ground_homography(matrix, CAMERA_HEIGHT_M)

  for x, y in ((5.0, -1.75), (10.0, 1.75), (40.0, -5.25)):
    # metric_marking.project_model_lane_metric_samples applies the matrix to (x, y, z).
    expected = matrix @ np.array((x, y, -CAMERA_HEIGHT_M))
    actual = homography @ np.array((x, y, 1.0))
    assert np.allclose(actual, expected)
    # ... and divides by the depth to get an image pixel.
    assert actual[0] / actual[2] == pytest.approx(PRINCIPAL_X + FOCAL * y / x)
    assert actual[1] / actual[2] == pytest.approx(PRINCIPAL_Y + FOCAL * CAMERA_HEIGHT_M / x)


def test_vehicle_and_image_round_trip():
  homography = ground_homography(camera_matrix(), CAMERA_HEIGHT_M)
  ground = [(x, y) for x in (6.0, 12.5, 25.0, 40.0) for y in (-5.25, -1.75, 0.0, 1.75, 5.25)]

  pixels = vehicle_to_image(homography, ground)
  recovered = image_to_vehicle(homography, pixels)

  assert len(pixels) == len(ground) and len(recovered) == len(ground)
  for (expected_x, expected_y), (actual_x, actual_y) in zip(ground, recovered, strict=True):
    assert actual_x == pytest.approx(expected_x, abs=1e-6)
    assert actual_y == pytest.approx(expected_y, abs=1e-6)


def test_a_straight_lane_line_recovers_its_lateral_offset_and_depth():
  homography = ground_homography(camera_matrix(), CAMERA_HEIGHT_M)
  line = [(float(x), -1.75) for x in np.linspace(5.0, 40.0, 9)]

  observation = boundary_observation_from_image(
    3, vehicle_to_image(homography, line), homography,
    marking_type=LaneMarkingType.dashed, confidence=0.8,
  )

  assert observation is not None and observation.source_id == 3
  assert observation.marking_type is LaneMarkingType.dashed and observation.confidence == 0.8
  assert observation.points[0][0] == pytest.approx(5.0, abs=1e-6)
  assert observation.points[-1][0] == pytest.approx(40.0, abs=1e-6)
  assert all(abs(y + 1.75) < 1e-6 for _, y in observation.points)


def test_the_horizon_has_no_ground_position_and_is_refused():
  homography = ground_homography(camera_matrix(), CAMERA_HEIGHT_M)

  # The vanishing point of the forward direction is exactly the principal point.
  assert image_to_vehicle(homography, [horizon_pixel()]) == ()
  assert image_to_vehicle(homography, [point_above_the_horizon()]) == ()
  # Below the horizon there is a finite ground intersection.
  below = image_to_vehicle(homography, [(PRINCIPAL_X, PRINCIPAL_Y + 40.0)])
  assert len(below) == 1 and below[0][0] > 0.0


def test_a_boundary_needs_two_placeable_points():
  homography = ground_homography(camera_matrix(), CAMERA_HEIGHT_M)
  above = point_above_the_horizon()

  assert boundary_observation_from_image(1, [], homography) is None
  assert boundary_observation_from_image(1, [above, above], homography) is None
  assert boundary_observation_from_image(1, [above, (PRINCIPAL_X, PRINCIPAL_Y + 40.0),
                                             (PRINCIPAL_X + 30.0, PRINCIPAL_Y + 60.0)], homography) is not None


def test_the_distance_window_bounds_what_may_be_claimed():
  homography = ground_homography(camera_matrix(), CAMERA_HEIGHT_M)
  far = vehicle_to_image(homography, [(70.0, 0.0)])
  assert len(far) == 1

  assert image_to_vehicle(homography, far, max_distance_m=60.0) == ()
  assert len(image_to_vehicle(homography, far, max_distance_m=80.0)) == 1
  assert boundary_observation_from_image(1, far * 2, homography, max_distance_m=60.0) is None


def test_degenerate_or_out_of_range_input_is_refused():
  with pytest.raises(ValueError):
    ground_homography(camera_matrix(), 0.1)
  with pytest.raises(ValueError):
    ground_homography(camera_matrix(), 5.0)
  with pytest.raises(ValueError):
    ground_homography(camera_matrix(), float('nan'))
  with pytest.raises(ValueError):
    ground_homography(camera_matrix(), True)
  with pytest.raises(ValueError):
    ground_homography(np.zeros((3, 3)), CAMERA_HEIGHT_M)
  with pytest.raises(ValueError):
    ground_homography(np.eye(2), CAMERA_HEIGHT_M)

  homography = ground_homography(camera_matrix(), CAMERA_HEIGHT_M)
  with pytest.raises(ValueError):
    image_to_vehicle(homography, [(1.0, 2.0)], min_distance_m=10.0, max_distance_m=5.0)
  with pytest.raises(ValueError):
    vehicle_to_image(homography, [(float('inf'), 0.0)])
  with pytest.raises(ValueError):
    vehicle_to_image(np.zeros((3, 3)), [(1.0, 1.0)])
  with pytest.raises(ValueError):
    boundary_observation_from_image(-1, [(1.0, 2.0), (3.0, 4.0)], homography)
