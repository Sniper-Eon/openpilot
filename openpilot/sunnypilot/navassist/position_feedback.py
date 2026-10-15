"""Display-only absolute lane feedback; visible-only observations are insufficient."""
from pathlib import Path
import json
import time

POSITION_PATH = Path('/dev/shm/road_lane_position.json')
MAX_AGE_MS = 2000
REQUEST_TYPE = 'lane_position_request'


def lane_position_feedback(snapshot, *, path: Path = POSITION_PATH, now_ns: int | None = None) -> dict:
  unknown = {'version': 1, 'valid': False, 'laneIndex': None, 'laneCount': None,
             'numbering': 'leftToRight', 'source': 'commaCamera', 'ageMs': 0,
             'validForMs': MAX_AGE_MS, 'routeRevision': snapshot.route_revision}
  try:
    if path.stat().st_size > 4096:
      return unknown
    d = json.loads(path.read_text())
    current = time.monotonic_ns() if now_ns is None else now_ns
    captured = d.get('capture_mono_ns')
    index, count = d.get('lane_index'), d.get('lane_count')
    if (type(captured) is not int or not 0 <= current-captured < MAX_AGE_MS*1_000_000 or
        type(d.get('version')) is not int or d['version'] != 1 or d.get('valid') is not True or d.get('absolute_confirmed') is not True or
        d.get('numbering') != 'leftToRight' or d.get('nav_session_id') != snapshot.session_id or
        type(d.get('route_revision')) is not int or d['route_revision'] != snapshot.route_revision or
        type(d.get('stable_samples')) is not int or d['stable_samples'] < 3 or
        type(index) is not int or not 1 <= index <= 12 or
        (count is not None and (type(count) is not int or not index <= count <= 12))):
      return unknown
    return unknown | {'valid': True, 'laneIndex': index, 'laneCount': count,
                      'ageMs': (current-captured+999_999)//1_000_000}
  except (OSError, ValueError, TypeError, AttributeError):
    return unknown
