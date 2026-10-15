from __future__ import annotations

import time
import cv2
import numpy as np

from openpilot.sunnypilot.lane_topology.external.protocol import VERSION, validate_frame


def letterbox(image: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
  h, w = image.shape[:2]
  if h < 32 or w < 32 or h > 2160 or w > 3840:
    raise ValueError('image dimensions out of range')
  scale = min(640 / w, 384 / h)
  nw, nh = round(w * scale), round(h * scale)
  x, y = (640 - nw) // 2, (384 - nh) // 2
  canvas = np.full((384, 640, 3), 114, dtype=np.uint8)
  canvas[y:y + nh, x:x + nw] = cv2.resize(image, (nw, nh))
  return canvas, (x, y, nw, nh)


def trace_boundaries(mask: np.ndarray, road: np.ndarray, *, reference_y: float) -> list[list[list[float]]]:
  """Trace probability-mask ridges across rows; no road-edge/global-index claim."""
  h, w = mask.shape
  if road.shape != mask.shape:
    raise ValueError('mask shape mismatch')
  tracks: list[list[tuple[float, float]]] = []
  ys = np.linspace(min(0.95, reference_y + 0.16), max(0.46, reference_y - 0.20), 16)
  for y in ys:
    row = min(h - 1, round(y * h))
    band = mask[max(0, row - 4):min(h, row + 5)]
    support = (band > 0.60).mean(axis=0) > 0.2
    columns = np.flatnonzero(support)
    groups = np.split(columns, np.flatnonzero(np.diff(columns) > 4) + 1)
    centers = [float(g.mean()) / w for g in groups if 1 <= len(g) <= w * 0.06]
    used = set()
    for x in centers:
      # The drivable mask is a weak observation filter, never a road boundary.
      if road[max(0, row - 2):min(h, row + 3), max(0, int(x*w)-8):min(w, int(x*w)+9)].max() < 0.4:
        continue
      candidates = []
      for i, track in enumerate(tracks):
        if i in used or abs(y - track[-1][1]) > 0.10:
          continue
        predicted = track[-1][0]
        if len(track) > 1:
          dx = track[-1][0] - track[-2][0]
          dy = track[-1][1] - track[-2][1]
          if abs(dy) > 1e-5:
            predicted += dx / dy * (y - track[-1][1])
        distance = abs(predicted - x)
        if distance < 0.065:
          candidates.append((distance, i))
      if candidates:
        _, i = min(candidates)
        tracks[i].append((x, float(y)))
        used.add(i)
      else:
        tracks.append([(x, float(y))])
        used.add(len(tracks) - 1)
  curves = []
  for track in tracks:
    if len(track) < 6 or not min(p[1] for p in track) <= reference_y <= max(p[1] for p in track):
      continue
    yy = np.array([p[1] for p in track])
    xx = np.array([p[0] for p in track])
    coefficients = np.polyfit(yy, xx, 2)
    if float(np.max(np.abs(np.polyval(coefficients, yy) - xx))) > 0.025:
      continue
    points = [[float(np.clip(np.polyval(coefficients, y), 0, 1)), float(y)]
              for y in np.linspace(float(yy.min()), float(yy.max()), 16)]
    x_ref = float(np.polyval(coefficients, reference_y))
    curves.append((x_ref, points))
  curves.sort(key=lambda p: p[0])
  deduplicated = []
  for x, points in curves:
    if not deduplicated or x - deduplicated[-1][0] > 0.025:
      deduplicated.append((x, points))
  return [points for _, points in deduplicated[:13]]


def observation(frame: dict, boundaries: list, inference_ms: float) -> dict:
  validate_frame(frame)
  x, y = frame['ego_point']
  positioned = [(float(np.interp(y, [p[1] for p in line], [p[0] for p in line])), line)
                for line in boundaries]
  positioned.sort(key=lambda item: item[0])
  positions = [p[0] for p in positioned]
  index = next((i for i in range(len(positions)-1) if positions[i] < x < positions[i+1]), -1)
  gaps = np.diff(positions)
  valid = bool(index >= 0 and len(gaps) > 0 and np.min(gaps) > 0.035 and
               np.max(gaps) <= 2.0 * np.median(gaps))
  return {
    **{k: frame[k] for k in ('session', 'sequence', 'frame_id', 'capture_mono_ns', 'ego_point', 'camera')},
    'version': VERSION, 'valid': valid, 'visible_lane_count': len(gaps) if valid else 0,
    'ego_lane_index': index if valid else -1, 'absolute_confirmed': False,
    'score': min(0.85, 0.5 + 0.05 * len(gaps)) if valid else 0.0,
    'inference_ms': float(inference_ms), 'reason': 'visibleEstimate' if valid else 'ambiguous',
    'boundaries': [p[1] for p in positioned],
  }


class YOLOPv2:
  """Loads the upstream TorchScript graph; no driving-model or GPU ownership."""
  def __init__(self, weights: str, *, device: str = 'cpu', threads: int = 2):
    import torch
    cv2.setNumThreads(1)
    self.torch = torch
    torch.set_num_threads(threads)
    self.device = device
    self.model = torch.jit.load(weights, map_location='cpu').eval().to(device).float()

  def infer(self, image: np.ndarray, frame: dict) -> dict:
    validate_frame(frame)
    started = time.perf_counter()
    padded, (x, y, w, h) = letterbox(image)
    tensor = self.torch.from_numpy(np.ascontiguousarray(padded[:, :, ::-1].transpose(2, 0, 1))).float()[None] / 255.0
    with self.torch.inference_mode():
      _, road, lanes = self.model(tensor.to(self.device))
      road = self.torch.softmax(road.float(), dim=1)[0, 1].cpu().numpy()
      lanes = lanes.float()[0, 0].cpu().numpy()
    road = cv2.resize(road, (640, 384))[y:y+h, x:x+w]
    lanes = cv2.resize(lanes, (640, 384))[y:y+h, x:x+w]
    # Work in a bounded image coordinate system; camera point is normalized.
    road, lanes = cv2.resize(road, (640, 384)), cv2.resize(lanes, (640, 384))
    boundaries = trace_boundaries(lanes, road, reference_y=frame['ego_point'][1])
    return observation(frame, boundaries, (time.perf_counter() - started) * 1000)
