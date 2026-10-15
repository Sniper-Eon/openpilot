import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.sunnypilot.lane_topology.external.perception import letterbox
from openpilot.sunnypilot.lane_topology.external.sender import export_nv12
from openpilot.sunnypilot.lane_topology.ground_projection import (
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  boundary_observation_from_image,
  canvas_point_to_ground,
  canvas_to_source_pixel,
  frame_geometry,
  ground_homography,
  image_to_vehicle,
  source_pixel_to_canvas,
  vehicle_to_image,
)
from openpilot.sunnypilot.lane_topology.types import LaneMarkingType

ROOT = Path(__file__).resolve().parents[4]

NATIVE_WIDTH, NATIVE_HEIGHT = 1920, 1080
FOCAL = 300.0
PRINCIPAL_X, PRINCIPAL_Y = 320.0, 192.0
CAMERA_HEIGHT_M = 1.2


def camera_matrix() -> np.ndarray:
  """The shipped convention: intrinsics @ view_from_calib over camera-centred (x, y, z).

  The calibration frame is ``x`` forward, ``y`` right, ``z`` down, so the road
  surface is the plane ``z = +camera_height``.
  """
  intrinsics = np.array(((FOCAL, 0.0, PRINCIPAL_X), (0.0, FOCAL, PRINCIPAL_Y), (0.0, 0.0, 1.0)))
  view_from_calib = np.array(((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)))
  return intrinsics @ view_from_calib


def horizon_pixel() -> tuple[float, float]:
  return PRINCIPAL_X, PRINCIPAL_Y


def point_above_the_horizon() -> tuple[float, float]:
  """A pixel of a point floating above the camera.

  ``z`` is down in the calibration frame, so a negative ``z`` is above the camera
  and the ray never meets the road plane at ``z = +camera_height``.
  """
  projected = camera_matrix() @ np.array((10.0, 0.0, -2.0))
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
    expected = matrix @ np.array((x, y, CAMERA_HEIGHT_M))
    actual = homography @ np.array((x, y, 1.0))
    assert np.allclose(actual, expected)
    # ... and divides by the depth to get an image pixel.
    assert actual[0] / actual[2] == pytest.approx(PRINCIPAL_X + FOCAL * y / x)
    assert actual[1] / actual[2] == pytest.approx(PRINCIPAL_Y + FOCAL * CAMERA_HEIGHT_M / x)


def test_the_homography_reproduces_the_device_calibrated_ego_point():
  """Anchored to the device, not to this module's own assumptions.

  The 2026-10-15 road-test sample carries the real extrinsicsCalibration. The
  device projects the ground point 10 m ahead with the same matrix and reports
  it as the ego point, so the homography must land on exactly that pixel. A sign
  error in the ground plane passes every self-consistent test and fails this one.
  """
  from openpilot.common.transformations.camera import DEVICE_CAMERAS, view_frame_from_device_frame
  from openpilot.common.transformations.orientation import rot_from_euler

  rpy_calib = (-6.535845022881404e-05, -0.021342530846595764, 0.008498449809849262)
  wide_from_device = (-2.1014362516780238e-07, 0.04605923965573311, -0.014795083552598953)
  height = 1.2537217140197754
  camera = DEVICE_CAMERAS[('unknown', 'ox03c10')].wide_road
  matrix = (camera.intrinsics @ view_frame_from_device_frame
            @ rot_from_euler(wide_from_device) @ rot_from_euler(rpy_calib))

  pixels = vehicle_to_image(ground_homography(matrix, height), [(10.0, 0.0)])

  assert len(pixels) == 1
  assert pixels[0][0] == pytest.approx(0.4981 * camera.width, abs=0.5)
  assert pixels[0][1] == pytest.approx(0.5471 * camera.height, abs=0.5)
  # The wrong sign puts the road plane above the camera and lands ~142 px high.
  flipped = matrix[:, :2].tolist()
  wrong = np.column_stack((np.array(flipped), matrix[:, 2] * -height))
  assert abs((wrong @ np.array((10.0, 0.0, 1.0)))[1] / (wrong @ np.array((10.0, 0.0, 1.0)))[2]
             - 0.5471 * camera.height) > 100.0


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


def native_camera_matrix(width: int = NATIVE_WIDTH, height: int = NATIVE_HEIGHT) -> np.ndarray:
  """The synthetic camera at the native frame size the calibration is expressed in."""
  focal = FOCAL * width / CANVAS_WIDTH
  intrinsics = np.array(((focal, 0.0, width / 2), (0.0, focal, height / 2), (0.0, 0.0, 1.0)))
  # x forward, y right, z down in the calibration frame.
  view_from_calib = np.array(((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)))
  return intrinsics @ view_from_calib


def fake_nv12_frame(width: int, height: int) -> SimpleNamespace:
  stride = width
  uv_offset = stride * height
  data = np.zeros(uv_offset + stride * (height // 2), dtype=np.uint8).tobytes()
  return SimpleNamespace(data=data, width=width, height=height, stride=stride, uv_offset=uv_offset)


def test_the_canvas_geometry_matches_the_two_resizers_that_actually_run():
  for width, height in ((1920, 1080), (1280, 960), (640, 384), (1152, 864), (720, 480)):
    geometry = frame_geometry(width, height)

    # The sender's downscale, checked by running it.
    exported = export_nv12(fake_nv12_frame(width, height))
    assert (exported['width'], exported['height']) == (geometry.export_width, geometry.export_height)

    # The observer's letterbox, which runs on the already-downscaled frame.
    _, (offset_x, offset_y, scaled_width, scaled_height) = letterbox(
      np.zeros((geometry.export_height, geometry.export_width, 3), dtype=np.uint8))
    assert (offset_x, offset_y) == (geometry.offset_x, geometry.offset_y)
    assert (scaled_width, scaled_height) == (geometry.scaled_width, geometry.scaled_height)


def test_a_native_pixel_survives_the_canvas_round_trip():
  geometry = frame_geometry(NATIVE_WIDTH, NATIVE_HEIGHT)
  assert (geometry.export_width, geometry.export_height) == (640, 360)
  assert (geometry.offset_x, geometry.offset_y) == (0, 12)

  for pixel in ((960.0, 700.0), (100.0, 900.0), (1800.0, 500.0)):
    canvas = source_pixel_to_canvas(geometry, pixel)
    assert 0.0 <= canvas[0] <= 1.0 and 0.0 <= canvas[1] <= 1.0
    recovered = canvas_to_source_pixel(geometry, canvas)
    assert recovered[0] == pytest.approx(pixel[0], abs=1e-6)
    assert recovered[1] == pytest.approx(pixel[1], abs=1e-6)


def test_a_canvas_point_maps_back_to_the_ground_position_it_came_from():
  matrix = native_camera_matrix()
  geometry = frame_geometry(NATIVE_WIDTH, NATIVE_HEIGHT)
  homography = ground_homography(matrix, CAMERA_HEIGHT_M)
  ground = [(8.0, -1.75), (20.0, 0.0), (35.0, 3.5)]

  pixels = vehicle_to_image(homography, ground)
  assert len(pixels) == len(ground)
  for (expected_x, expected_y), pixel in zip(ground, pixels, strict=True):
    canvas = source_pixel_to_canvas(geometry, pixel)
    recovered = canvas_point_to_ground(geometry, canvas, matrix, CAMERA_HEIGHT_M)
    assert recovered is not None
    assert recovered[0] == pytest.approx(expected_x, abs=1e-6)
    assert recovered[1] == pytest.approx(expected_y, abs=1e-6)


def test_the_letterbox_margin_is_padding_and_never_a_road_point():
  matrix = native_camera_matrix()
  geometry = frame_geometry(NATIVE_WIDTH, NATIVE_HEIGHT)
  margin = (0.5, (geometry.offset_y - 1) / CANVAS_HEIGHT)

  with pytest.raises(ValueError):
    canvas_to_source_pixel(geometry, margin)
  with pytest.raises(ValueError):
    canvas_point_to_ground(geometry, margin, matrix, CAMERA_HEIGHT_M)
  # A point below the horizon, inside the frame, is accepted.
  ten_metres_ahead = (geometry.offset_y + 216) / CANVAS_HEIGHT
  placed = canvas_point_to_ground(geometry, (0.5, ten_metres_ahead), matrix, CAMERA_HEIGHT_M)
  assert placed is not None and placed[0] == pytest.approx(10.0, abs=1e-6)


def test_out_of_range_frame_dimensions_are_refused():
  for width, height in ((30, 384), (640, 30), (4000, 1080), (1920, 3000), (1920.0, 1080), (None, 1080)):
    with pytest.raises(ValueError):
      frame_geometry(width, height)
  # A native frame that needs no downscale still produces a usable geometry.
  native = frame_geometry(640, 384)
  assert (native.export_width, native.export_height) == (640, 384)
  assert (native.offset_x, native.offset_y) == (0, 0)
  # An odd native height is rounded down to the even export size the sender produces.
  assert frame_geometry(640, 481).export_height == 480


def test_canvas_pairs_must_be_finite_pairs():
  geometry = frame_geometry(NATIVE_WIDTH, NATIVE_HEIGHT)
  for bad in ((0.5,), (0.5, 0.5, 0.5), (float('nan'), 0.5), (0.5, float('inf'))):
    with pytest.raises(ValueError):
      source_pixel_to_canvas(geometry, bad)
  with pytest.raises(ValueError):
    canvas_to_source_pixel(geometry, (0.5,))
  with pytest.raises(ValueError):
    canvas_to_source_pixel(geometry, (float('nan'), 0.5))
