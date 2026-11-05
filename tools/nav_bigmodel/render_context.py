"""Mac-side normalized route/GPS JSON -> official map + 47-vector -> atomic NPZ.

Each stdin line is a NEW qualified observation stamped by a producer on this
Mac. Never stamp a replay or an unchanged cached phone packet as live data.
Coordinates must already be WGS84. Raw phone GCJ02 input is rejected.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
from tools.nav_bigmodel.official_map.pmtiles import PMTiles
from tools.nav_bigmodel.official_map.renderer import MapRenderer
from tools.nav_bigmodel.official_map.route import RouteTracker

COMMANDS = {8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 27, 28}


class RangeSource:
  def __init__(self, url, cache):
    if not url.startswith('https://'):
      raise ValueError('Map archive must use HTTPS')
    self.url, self.cache = url, cache
    cache.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=10) as response:
      self.size = int(response.headers['Content-Length'])
      self.etag = response.headers.get('ETag')
    if not self.etag:
      raise ValueError('Map archive needs an ETag to prevent mixed revisions')
    self.key = hashlib.sha256((url + self.etag).encode()).hexdigest()

  def read(self, offset, length):
    if offset < 0 or length < 0 or offset + length > self.size or length > 8 << 20:
      raise ValueError('Invalid archive range')
    path = self.cache / f'{self.key}-{offset}-{length}'
    if path.exists():
      result = path.read_bytes()
      if len(result) == length:
        return result
    request = urllib.request.Request(self.url, headers={'Range': f'bytes={offset}-{offset+length-1}',
                                                        'If-Match': self.etag})
    with urllib.request.urlopen(request, timeout=10) as response:
      if response.status != 206:
        raise ValueError('Server ignored byte range')
      result = response.read(length + 1)
    if len(result) != length:
      raise ValueError('Incomplete map data')
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(result); temporary.replace(path)
    return result


def render(packet, renderer, tracker=None):
  stamp = packet.get('captured_monotonic_ns', 0) / 1e9
  if packet.get('active') is not True or packet.get('coordinate_system') != 'wgs84':
    raise ValueError('Active WGS84 route required')
  transit = time.monotonic() - stamp
  if not 0 <= transit < 0.5:
    raise ValueError('Expired observation; timestamp must use this Mac monotonic clock')
  position = packet['position']
  age = float(position['age_ms']) / 1000
  if position.get('has_fix') is not True or not 0 <= age or not age + transit < 2:
    raise ValueError('Unqualified position')
  age += transit
  route = np.asarray(packet['route'], dtype=np.float64)
  if route.ndim != 2 or route.shape[1] != 2 or not 2 <= len(route) <= 100000 or not np.isfinite(route).all():
    raise ValueError('Invalid route')
  if (np.abs(route[:, 0]) > 180).any() or (np.abs(route[:, 1]) >= 85).any():
    raise ValueError('Route coordinates outside renderer range')
  lon, lat, speed = (float(position[k]) for k in ('longitude', 'latitude', 'speed_mps'))
  if not np.isfinite([lon, lat, speed]).all() or abs(lon) > 180 or abs(lat) >= 85:
    raise ValueError('Invalid position')
  if tracker is None or not np.array_equal(tracker.route, route):
    tracker = RouteTracker(route)
  pose = tracker.pose(tracker.project(lon, lat) + max(speed, 0) * age)
  image, valid = renderer.render(*pose, route)
  if not valid:
    image[:] = 0
  nav = np.zeros((1, 47), np.float32)
  guidance = packet.get('guidance', {})
  guidance_age = float(guidance.get('age_ms', -1)) / 1000
  if guidance.get('valid') is True and 0 <= guidance_age and guidance_age + transit < 2:
    command, distance = guidance.get('command'), float(guidance.get('distance_m', -1))
    if type(command) is int and command in COMMANDS and np.isfinite(distance) and distance >= 0:
      nav[0, command], nav[0, 46] = 1, distance / 100
  return image.astype(np.float32)[None, None], nav, stamp, tracker


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--archive-url', required=True)
  parser.add_argument('--cache', required=True, type=Path)
  parser.add_argument('--output', required=True, type=Path)
  args = parser.parse_args()
  renderer = MapRenderer(PMTiles(RangeSource(args.archive_url, args.cache)))
  tracker = None
  args.output.parent.mkdir(parents=True, exist_ok=True)
  for line in sys.stdin:
    try:
      if len(line) > 8_000_000:
        raise ValueError('Oversized observation')
      image, nav, stamp, tracker = render(json.loads(line), renderer, tracker)
      if not 0 <= time.monotonic() - stamp < 0.5:
        raise ValueError('Rendering exceeded observation lifetime')
      with tempfile.NamedTemporaryFile(dir=args.output.parent, suffix='.npz', delete=False) as out:
        name = out.name
        np.savez(out, nav_map=image, navigation=nav, captured_monotonic_ns=np.int64(stamp * 1e9))
      os.replace(name, args.output)
    except Exception as error:
      args.output.unlink(missing_ok=True)
      tracker = None
      print(type(error).__name__ + ': navigation context cleared', file=sys.stderr)
  args.output.unlink(missing_ok=True)


if __name__ == '__main__': main()
