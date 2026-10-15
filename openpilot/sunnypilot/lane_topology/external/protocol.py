from __future__ import annotations

import json
import math
from pathlib import Path
import time

VERSION = 1
MAX_BODY = 800_000
MAX_RESPONSE = 32_768
MAX_AGE_NS = 2_000_000_000
RESULT_PATH = Path('/dev/shm/external_lane_observation.json')
CONFIG_PATH = Path('/data/navassist/external_lane.json')


def integer(value, low: int, high: int) -> int:
  if type(value) is not int or not low <= value <= high:
    raise ValueError('integer out of range')
  return value


def number(value, low: float, high: float) -> float:
  if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
    raise ValueError('number out of range')
  return float(value)


def validate_frame(value: dict) -> dict:
  if not isinstance(value, dict) or (type(value.get('version')) is not int or value['version'] != VERSION):
    raise ValueError('unsupported frame')
  session = value.get('session')
  if not isinstance(session, str) or len(session) != 32 or any(c not in '0123456789abcdef' for c in session):
    raise ValueError('invalid session')
  for key in ('sequence', 'frame_id', 'capture_mono_ns'):
    integer(value.get(key), 1 if key != 'frame_id' else 0, 2**63 - 1)
  ego = value.get('ego_point')
  if not isinstance(ego, list) or len(ego) != 2:
    raise ValueError('missing calibrated ego point')
  number(ego[0], 0.1, 0.9)
  number(ego[1], 0.45, 0.95)
  if value.get('camera') != 'wideRoad':
    raise ValueError('requires wide camera')
  return value


def validate_result(value: dict, frame: dict, *, now_ns: int) -> dict:
  validate_frame(frame)
  if not isinstance(value, dict) or (type(value.get('version')) is not int or value['version'] != VERSION):
    raise ValueError('unsupported result')
  for key in ('session', 'sequence', 'frame_id', 'capture_mono_ns', 'ego_point', 'camera'):
    if value.get(key) != frame[key]:
      raise ValueError('response does not match outstanding frame')
  age = now_ns - frame['capture_mono_ns']
  if not 0 <= age <= MAX_AGE_NS:
    raise ValueError('expired frame')
  if type(value.get('valid')) is not bool or value.get('absolute_confirmed') is not False:
    raise ValueError('this observer cannot authorize an absolute lane or control')
  count = integer(value.get('visible_lane_count'), 0, 12)
  index = integer(value.get('ego_lane_index'), -1, 11)
  if value['valid'] and not (count > 0 and 0 <= index < count):
    raise ValueError('invalid lane index')
  if not value['valid'] and (count != 0 or index != -1):
    raise ValueError('invalid observation must clear its index')
  number(value.get('score'), 0, 1)
  number(value.get('inference_ms'), 0, 30_000)
  reason = value.get('reason')
  if not isinstance(reason, str) or len(reason) > 64:
    raise ValueError('invalid reason')
  boundaries = value.get('boundaries')
  if not isinstance(boundaries, list) or len(boundaries) > 13:
    raise ValueError('too many boundaries')
  for line in boundaries:
    if not isinstance(line, list) or not 2 <= len(line) <= 32:
      raise ValueError('invalid boundary')
    for point in line:
      if not isinstance(point, list) or len(point) != 2:
        raise ValueError('invalid point')
      number(point[0], 0, 1)
      number(point[1], 0, 1)
  # Whitelist the small result; never store server-supplied paths or commands.
  keys = ('version', 'session', 'sequence', 'frame_id', 'capture_mono_ns', 'valid',
          'visible_lane_count', 'ego_lane_index', 'absolute_confirmed', 'score',
          'inference_ms', 'reason', 'boundaries', 'ego_point', 'camera')
  return {key: value[key] for key in keys}


class ResultCache:
  def __init__(self, path: Path = RESULT_PATH):
    self.path = path
    self.next_read = 0.0
    self.value: dict | None = None

  def read(self, *, now_ns: int | None = None) -> dict | None:
    now_ns = time.monotonic_ns() if now_ns is None else now_ns
    if time.monotonic() >= self.next_read:
      self.next_read = time.monotonic() + 0.2
      try:
        if self.path.stat().st_size > MAX_RESPONSE:
          raise ValueError('oversized result')
        raw = json.loads(self.path.read_text())
        self.value = validate_result(raw, raw, now_ns=now_ns)
      except (OSError, ValueError, TypeError, KeyError, OverflowError):
        self.value = None
    if self.value is None or not 0 <= now_ns - self.value['capture_mono_ns'] <= MAX_AGE_NS:
      return None
    return self.value if self.value['valid'] else None
