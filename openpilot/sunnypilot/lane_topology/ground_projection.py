"""Ground-plane projection between image points and vehicle metres.

The external observer returns boundary polylines in image coordinates, while the
absolute-lane evidence gate needs vehicle metres (``x`` forward, ``y``
left-positive). For a known camera matrix and camera height the road surface is a
plane, so a 3x3 homography maps it exactly.

The calibration frame that ``camera_from_calib = intrinsics @ view_from_calib``
acts on is ``x`` forward, ``y`` right, ``z`` **down**, so the road surface sits at
``z = +camera_height``. Measured on the 2026-10-15 road-test sample, modelV2 lane
line ``z`` has median +1.243 m against a calibrated height of 1.2537 m, and only
``+height`` reproduces the device's own ``calibrated_ego_point`` for a point 10 m
ahead; ``-height`` lands 142 px too high. Getting this sign wrong silently puts
the road plane above the camera.

Only the projection and the canvas geometry are provided here. This module does
not measure or classify a single lane marking, and no camera matrix has been
checked against a real frame, so on its own it cannot produce an absolute lane.
Points at or above the horizon have no finite ground position and are refused
rather than extrapolated.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from openpilot.sunnypilot.lane_topology.types import LaneBoundaryObservation, LaneMarkingType

MIN_CAMERA_HEIGHT_M = 0.5
MAX_CAMERA_HEIGHT_M = 3.0
MIN_HOMOGRAPHY_DETERMINANT = 1e-12
MAX_GROUND_DISTANCE_M = 80.0
MIN_DEPTH = 1e-6


def ground_homography(camera_from_calib, camera_height_m: float) -> np.ndarray:
  """Return the 3x3 homography mapping ground ``(x, y, 1)`` to image pixels.

  ``camera_from_calib`` is the 3x3 matrix that maps a calibration-frame point
  ``(x_forward, y_right, z_down)`` to homogeneous pixels, exactly as
  ``metric_marking.project_model_lane_metric_samples`` applies it. The ground
  plane sits at ``z = +camera_height_m``.
  """
  matrix = np.asarray(camera_from_calib, dtype=np.float64)
  if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
    raise ValueError('camera_from_calib must be a finite 3x3 matrix')
  if type(camera_height_m) not in (int, float) or not math.isfinite(camera_height_m) or \
      not MIN_CAMERA_HEIGHT_M <= camera_height_m <= MAX_CAMERA_HEIGHT_M:
    raise ValueError(f'camera height must be a finite number within '
                     f'[{MIN_CAMERA_HEIGHT_M}, {MAX_CAMERA_HEIGHT_M}] metres')
  # (u_num, v_num, depth) = M @ (x, y, +h) = M[:, :2] @ (x, y) + M[:, 2] * +h
  homography = np.empty((3, 3), dtype=np.float64)
  homography[:, :2] = matrix[:, :2]
  homography[:, 2] = matrix[:, 2] * float(camera_height_m)
  if abs(float(np.linalg.det(homography))) < MIN_HOMOGRAPHY_DETERMINANT:
    raise ValueError('degenerate ground-plane mapping')
  return homography


def _homogeneous_project(homography: np.ndarray, points) -> tuple[tuple[float, float], ...]:
  projected: list[tuple[float, float]] = []
  for point in points:
    if not isinstance(point, (tuple, list, np.ndarray)) or len(point) != 2:
      raise ValueError('each point must be a pair')
    x, y = float(point[0]), float(point[1])
    if not (math.isfinite(x) and math.isfinite(y)):
      raise ValueError('points must be finite')
    vector = homography @ np.array((x, y, 1.0))
    if vector[2] <= MIN_DEPTH:
      continue
    projected.append((float(vector[0] / vector[2]), float(vector[1] / vector[2])))
  return tuple(projected)


def vehicle_to_image(homography, points) -> tuple[tuple[float, float], ...]:
  """Project finite ground points to image pixels; drop anything behind the camera."""
  return _homogeneous_project(_validated_homography(homography), points)


def image_to_vehicle(homography, points, *, min_distance_m: float = 0.0,
                     max_distance_m: float = MAX_GROUND_DISTANCE_M) -> tuple[tuple[float, float], ...]:
  """Invert the ground homography, refusing the horizon and out-of-range depths."""
  if not 0.0 <= min_distance_m < max_distance_m <= MAX_GROUND_DISTANCE_M:
    raise ValueError('invalid ground distance window')
  inverse = np.linalg.inv(_validated_homography(homography))
  ground: list[tuple[float, float]] = []
  for point in points:
    if not isinstance(point, (tuple, list, np.ndarray)) or len(point) != 2:
      raise ValueError('each point must be a pair')
    u, v = float(point[0]), float(point[1])
    if not (math.isfinite(u) and math.isfinite(v)):
      raise ValueError('points must be finite')
    vector = inverse @ np.array((u, v, 1.0))
    if vector[2] <= MIN_DEPTH:
      # At or above the horizon the plane intersection is at infinity or behind.
      continue
    x, y = float(vector[0] / vector[2]), float(vector[1] / vector[2])
    if math.isfinite(x) and math.isfinite(y) and min_distance_m <= x <= max_distance_m:
      ground.append((x, y))
  return tuple(ground)


def boundary_observation_from_image(source_id: int, points, homography, *,
                                    marking_type: LaneMarkingType = LaneMarkingType.unknown,
                                    confidence: float = 0.0,
                                    max_distance_m: float = MAX_GROUND_DISTANCE_M
                                    ) -> LaneBoundaryObservation | None:
  """One image polyline as a metric boundary, or None when it cannot be placed."""
  if type(source_id) is not int or source_id < 0:
    raise ValueError('source_id must be a non-negative integer')
  ground = image_to_vehicle(homography, points, max_distance_m=max_distance_m)
  if len(ground) < 2:
    return None
  return LaneBoundaryObservation(source_id=source_id, points=ground, marking_type=marking_type,
                                 confidence=confidence)


def _validated_homography(homography) -> np.ndarray:
  matrix = np.asarray(homography, dtype=np.float64)
  if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
    raise ValueError('homography must be a finite 3x3 matrix')
  if abs(float(np.linalg.det(matrix))) < MIN_HOMOGRAPHY_DETERMINANT:
    raise ValueError('degenerate homography')
  return matrix


CANVAS_WIDTH = 640
CANVAS_HEIGHT = 384
MAX_EXPORT_WIDTH = 640
MAX_EXPORT_HEIGHT = 480
MIN_FRAME_SIDE = 32
MAX_FRAME_WIDTH = 3840
MAX_FRAME_HEIGHT = 2160


@dataclass(frozen=True)
class FrameGeometry:
  """Native camera frame -> the observer's 640x384 normalized canvas.

  The observer receives a frame that the sender already downscaled to at most
  640x480 and then fits into a 640x384 canvas with a centred margin. A boundary
  point comes back normalized to that canvas, so undoing both steps is required
  before any pixel can be mapped to the road. The offsets and sizes here mirror
  ``external.sender.export_nv12`` and ``external.perception.letterbox``, and
  ``test_ground_projection`` pins them against those two functions so the two
  cannot drift apart silently.
  """

  native_width: int
  native_height: int
  export_width: int
  export_height: int
  offset_x: int
  offset_y: int
  scaled_width: int
  scaled_height: int


def frame_geometry(native_width: int, native_height: int) -> FrameGeometry:
  if type(native_width) is not int or type(native_height) is not int:
    raise ValueError('frame dimensions must be integers')
  if not MIN_FRAME_SIDE <= native_width <= MAX_FRAME_WIDTH or \
      not MIN_FRAME_SIDE <= native_height <= MAX_FRAME_HEIGHT:
    raise ValueError('frame dimensions out of range')
  export_scale = min(MAX_EXPORT_WIDTH / native_width, MAX_EXPORT_HEIGHT / native_height, 1.0)
  export_width = int(native_width * export_scale) // 2 * 2
  export_height = int(native_height * export_scale) // 2 * 2
  if export_width < MIN_FRAME_SIDE or export_height < MIN_FRAME_SIDE:
    raise ValueError('unsupported camera aspect ratio')
  canvas_scale = min(CANVAS_WIDTH / export_width, CANVAS_HEIGHT / export_height)
  scaled_width = round(export_width * canvas_scale)
  scaled_height = round(export_height * canvas_scale)
  return FrameGeometry(
    native_width=native_width, native_height=native_height,
    export_width=export_width, export_height=export_height,
    offset_x=(CANVAS_WIDTH - scaled_width) // 2, offset_y=(CANVAS_HEIGHT - scaled_height) // 2,
    scaled_width=scaled_width, scaled_height=scaled_height,
  )


def source_pixel_to_canvas(geometry: FrameGeometry, pixel) -> tuple[float, float]:
  """A native-frame pixel as a point normalized to the 640x384 canvas."""
  u, v = _validated_pair(pixel)
  canvas_u = geometry.offset_x + u * geometry.scaled_width / geometry.native_width
  canvas_v = geometry.offset_y + v * geometry.scaled_height / geometry.native_height
  return canvas_u / CANVAS_WIDTH, canvas_v / CANVAS_HEIGHT


def canvas_to_source_pixel(geometry: FrameGeometry, point) -> tuple[float, float]:
  """Undo the canvas letterbox and the sender downscale to a native-frame pixel."""
  normalized_u, normalized_v = _validated_pair(point)
  canvas_u, canvas_v = normalized_u * CANVAS_WIDTH, normalized_v * CANVAS_HEIGHT
  if not geometry.offset_x <= canvas_u <= geometry.offset_x + geometry.scaled_width or \
      not geometry.offset_y <= canvas_v <= geometry.offset_y + geometry.scaled_height:
    # The letterbox margin is padding, never an observed road pixel.
    raise ValueError('point falls outside the letterboxed frame')
  u = (canvas_u - geometry.offset_x) * geometry.native_width / geometry.scaled_width
  v = (canvas_v - geometry.offset_y) * geometry.native_height / geometry.scaled_height
  return u, v


def canvas_point_to_ground(geometry: FrameGeometry, point, camera_from_calib, camera_height_m: float, *,
                           min_distance_m: float = 0.0,
                           max_distance_m: float = MAX_GROUND_DISTANCE_M
                           ) -> tuple[float, float] | None:
  """One normalized canvas point as a ground position, or None when unplaceable."""
  homography = ground_homography(camera_from_calib, camera_height_m)
  ground = image_to_vehicle(homography, [canvas_to_source_pixel(geometry, point)],
                            min_distance_m=min_distance_m, max_distance_m=max_distance_m)
  return ground[0] if ground else None


def _validated_pair(value) -> tuple[float, float]:
  if not isinstance(value, (tuple, list, np.ndarray)) or len(value) != 2:
    raise ValueError('expected a pair')
  first, second = float(value[0]), float(value[1])
  if not (math.isfinite(first) and math.isfinite(second)):
    raise ValueError('pair must be finite')
  return first, second
