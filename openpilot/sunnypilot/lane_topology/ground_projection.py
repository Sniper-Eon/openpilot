"""Ground-plane projection between image points and vehicle metres.

The external observer returns boundary polylines in image coordinates, while the
absolute-lane evidence gate needs vehicle metres (``x`` forward, ``y``
left-positive). For a known camera matrix and camera height the road surface is a
plane, so a 3x3 homography maps it exactly: the plane is ``z = -camera_height`` in
the camera-centred convention that ``camera_from_calib = intrinsics @
view_from_calib`` uses (see ``navassist/lane_topologyd.py`` and
``metric_marking.project_model_lane_metric_samples``).

Only the projection is provided here. This module does not measure or classify a
single lane marking, and no camera matrix has been checked against a real frame,
so on its own it cannot produce an absolute lane. Points at or above the horizon
have no finite ground position and are refused rather than extrapolated.
"""
from __future__ import annotations

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

  ``camera_from_calib`` is the 3x3 matrix that maps a camera-centred point
  ``(x_forward, y_left, z_up)`` to homogeneous pixels, exactly as
  ``metric_marking.project_model_lane_metric_samples`` applies it. The ground
  plane sits at ``z = -camera_height_m``.
  """
  matrix = np.asarray(camera_from_calib, dtype=np.float64)
  if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
    raise ValueError('camera_from_calib must be a finite 3x3 matrix')
  if type(camera_height_m) not in (int, float) or not math.isfinite(camera_height_m) or \
      not MIN_CAMERA_HEIGHT_M <= camera_height_m <= MAX_CAMERA_HEIGHT_M:
    raise ValueError(f'camera height must be a finite number within '
                     f'[{MIN_CAMERA_HEIGHT_M}, {MAX_CAMERA_HEIGHT_M}] metres')
  # (u_num, v_num, depth) = M @ (x, y, -h) = M[:, :2] @ (x, y) + M[:, 2] * -h
  homography = np.empty((3, 3), dtype=np.float64)
  homography[:, :2] = matrix[:, :2]
  homography[:, 2] = matrix[:, 2] * -float(camera_height_m)
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
