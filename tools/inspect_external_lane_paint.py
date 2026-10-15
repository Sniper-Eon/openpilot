#!/usr/bin/env python3
"""Measure paint features of the observer's traced curves on one frame.

Typing a curve as a lane marking is the missing half of the lane-anchored design:
the observer traces ridges from a lane mask, but a strong pavement or embankment
boundary also lights that mask up, and the road edge beyond the lanes must never
be counted as a lane. Deciding that needs a feature, and a feature needs numbers
before it needs a threshold.

This tool reports those numbers and deliberately does not classify anything: an
absolute brightness threshold would follow exposure rather than paint, and two
frames cannot calibrate a relative one. Use it on more frames to earn a rule.

Offline only: one image in, one JSON report out. No capture device, log stream,
message bus, parameter or vehicle interface is touched.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from openpilot.sunnypilot.lane_topology.external.perception import YOLOPv2

MAX_CURVES = 64
SHIFT_PX = 6
MASK_PRESENT = 0.6


def _index(points: np.ndarray, shape: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
  height, width = shape[0], shape[1]
  xs = np.clip(np.rint(points[:, 0] * width).astype(int), 0, width - 1)
  ys = np.clip(np.rint(points[:, 1] * height).astype(int), 0, height - 1)
  return xs, ys


def curve_features(*, gray: np.ndarray, hsv: np.ndarray, lane_mask: np.ndarray,
                   points, shift_px: int = SHIFT_PX) -> dict[str, Any]:
  """Along-curve paint features for one normalized polyline; no verdict.

  The polyline is normalized, so the same points index both the native image
  (colour) and the observer's smaller canvas (the lane mask). Their shapes are
  expected to differ; each is sampled with its own extent.
  """
  array = np.asarray(points, dtype=np.float64)
  if array.ndim != 2 or array.shape[1] != 2 or len(array) < 2:
    raise ValueError('a curve needs at least two normalised points')
  if gray.ndim != 2 or hsv.ndim != 3 or hsv.shape[:2] != gray.shape:
    raise ValueError('expected a grey image and a matching HSV image')
  if lane_mask.ndim != 2 or min(lane_mask.shape) < 2:
    raise ValueError('lane mask must be a 2D image')
  if not 0 <= int(shift_px) < gray.shape[1]:
    raise ValueError('shift must be a small positive pixel offset')

  # The mask lives on the observer canvas and the colour on the native frame, so
  # each is indexed with its own extent. Mixing them silently samples the wrong
  # pixels, which is how this tool first reported the wrong brightnesses.
  mask_x, mask_y = _index(array, lane_mask.shape)
  gray_x, gray_y = _index(array, gray.shape)
  paint = lane_mask[mask_y, mask_x] > MASK_PRESENT
  brightness = gray[gray_y, gray_x].astype(np.float64)
  saturation = hsv[gray_y, gray_x, 1].astype(np.float64)
  width = gray.shape[1]
  neighbours = np.concatenate((
    gray[gray_y, np.clip(gray_x - shift_px, 0, width - 1)],
    gray[gray_y, np.clip(gray_x + shift_px, 0, width - 1)],
  )).astype(np.float64)
  neighbour_level = float(np.median(neighbours))
  lit = np.flatnonzero(paint)
  return {
    'points': int(len(array)),
    'mask_coverage': float(paint.mean()),
    'mask_gaps': int(np.sum(np.diff(lit) > 1)) if len(lit) > 1 else 0,
    'median_brightness': float(np.median(brightness)),
    'median_saturation': float(np.median(saturation)),
    'contrast_vs_shift': float(np.median(brightness) - neighbour_level),
  }


def inspect_curves(*, gray: np.ndarray, hsv: np.ndarray, lane_mask: np.ndarray, curves,
                   shift_px: int = SHIFT_PX) -> list[dict[str, Any]]:
  """Features for every curve plus a within-frame brightness rank."""
  if len(curves) > MAX_CURVES:
    raise ValueError('too many curves')
  rows = [curve_features(gray=gray, hsv=hsv, lane_mask=lane_mask, points=curve, shift_px=shift_px)
          for curve in curves]
  order = sorted(range(len(rows)), key=lambda i: rows[i]['median_brightness'], reverse=True)
  for rank, index in enumerate(order):
    rows[index]['brightness_rank'] = rank
  return rows


def inspect_frame(image: np.ndarray, model, ego_point) -> dict[str, Any]:
  result, _, lane_mask = model.infer_with_masks(image, {
    'version': 1, 'session': '0' * 32, 'sequence': 1, 'frame_id': 0,
    'capture_mono_ns': 1, 'ego_point': [float(ego_point[0]), float(ego_point[1])], 'camera': 'wideRoad',
  })
  gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
  hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
  rows = inspect_curves(gray=gray, hsv=hsv, lane_mask=lane_mask, curves=result['boundaries'])
  for row, curve in zip(rows, result['boundaries'], strict=True):
    ys = [point[1] for point in curve]
    xs = [point[0] for point in curve]
    row['x_at_ego_row'] = float(np.interp(ego_point[1], ys, xs))
  return {'valid': result['valid'], 'visible_lane_count': result['visible_lane_count'],
          'ego_lane_index': result['ego_lane_index'], 'absolute_confirmed': False, 'curves': rows}


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('image', type=Path)
  parser.add_argument('--weights', type=Path, required=True)
  parser.add_argument('--ego-x', type=float, default=0.5)
  parser.add_argument('--ego-y', type=float, default=0.65,
                      help='reference row; on the device this is the calibrated ego point')
  parser.add_argument('--output', type=Path, help='write the report here instead of stdout')
  args = parser.parse_args()

  image = cv2.imread(str(args.image))
  if image is None:
    parser.error('image cannot be decoded')
  report = inspect_frame(image, YOLOPv2(str(args.weights)), (args.ego_x, args.ego_y))
  text = json.dumps(report, indent=2, sort_keys=True)
  if args.output:
    args.output.write_text(text + '\n')
  print(text)
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
