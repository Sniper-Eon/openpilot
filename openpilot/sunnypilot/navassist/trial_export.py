"""Private, default-off route observation export for Mac shadow inference.

No vehicle outputs. The approximate coordinate conversion is for experimental
map input only. A route is not absolute lane evidence. Commands remain zero
until the phone maneuver/reference-distance semantics are independently proven.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from openpilot.sunnypilot.navassist.route_geometry import gcj02_to_wgs84

PATH = Path('/dev/shm/jetlink_nav_context.json')


def observation(current, geometry, now_ns, wall_ms, enabled):
  if enabled is not True or current is None or geometry is None or current.is_stale(now_ns):
    raise ValueError('No qualified route')
  s, g = current.snapshot, geometry
  elapsed_ms = (now_ns-current.receive_mono_ns)/1e6
  location_age_ms = s.source_wall_time_ms-s.location_observed_at_ms
  delivery_age_ms = wall_ms-s.source_wall_time_ms
  if (s.navigation_mode != 'realtime' or not s.route_active or not s.route_matched or s.gps_weak
      or not 0 <= elapsed_ms < 500 or not 0 <= location_age_ms <= 1000
      or not 0 <= delivery_age_ms < 2000 or not 0 <= s.accuracy_m <= 25
      or (s.session_id, s.route_revision, s.coordinate_system) != (g.session_id, g.route_revision, g.coordinate_system)
      or not g.wgs84_points or s.coordinate_system not in ('gcj02', 'wgs84')):
    raise ValueError('Unqualified route or phone location')
  # Same-phone timestamps provide observation age. Wall time additionally bounds
  # delivery; negative skew is rejected, never silently relabelled as fresh.
  age = location_age_ms + max(delivery_age_ms, elapsed_ms)
  if age >= 2000:
    raise ValueError('Expired phone location')
  lat, lon = (gcj02_to_wgs84(s.latitude, s.longitude) if s.coordinate_system == 'gcj02'
              else (s.latitude, s.longitude))
  return dict(version=1, exported_monotonic_ns=now_ns, observation_monotonic_ns=current.receive_mono_ns,
              session_id=s.session_id, sequence=s.sequence, route_revision=s.route_revision, route_id=g.route_id,
              packet=dict(active=True, coordinate_system='wgs84', route=[[lon, lat] for lat, lon in g.wgs84_points],
                          position=dict(longitude=lon, latitude=lat, speed_mps=s.speed_kph/3.6, has_fix=True, age_ms=age),
                          guidance=dict(valid=False), conversion_approximate=s.coordinate_system == 'gcj02'))


class TrialExporter:
  def __init__(self, store, geometry, enabled, path=PATH):
    self.store, self.geometry, self.enabled, self.path = store, geometry, enabled, path
    self.stop = threading.Event()
    self.thread = threading.Thread(target=self.run, daemon=True, name='nav-trial-export')

  def run(self):
    while not self.stop.is_set():
      name = None
      try:
        now = time.monotonic_ns()
        current = self.store.current()
        result = observation(current, self.geometry.current(current, now), now, time.time_ns()//1_000_000, self.enabled())
        with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, delete=False) as out:
          name = out.name  # tempfile creates mode 0600; route/location stay private.
          json.dump(result, out, allow_nan=False, separators=(',', ':'))
        # Master may have changed during serialization.
        if self.enabled() is not True:
          raise ValueError('Disabled')
        os.replace(name, self.path)
        name = None
      except Exception:
        try:
          self.path.unlink(missing_ok=True)
        except OSError:
          pass
      finally:
        if name:
          try:
            Path(name).unlink(missing_ok=True)
          except OSError:
            pass
      self.stop.wait(.1)
    try:
      self.path.unlink(missing_ok=True)
    except OSError:
      pass

  def close(self):
    self.stop.set()
    if self.thread.ident is not None:
      self.thread.join(timeout=1)
