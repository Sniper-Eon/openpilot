"""Bounded two-camera transport. This file has no control/actuator interface."""
from collections import OrderedDict
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time

MAX_AGE_NS = 800_000_000


class DualCameraStore:
  def __init__(self, output, clock=time.monotonic_ns, max_skew_ns=50_000_000, stereo_sha256=None):
    self.output, self.clock = Path(output), clock
    self.max_skew_ns = max_skew_ns
    self.stereo_sha256 = stereo_sha256
    self.condition = threading.Condition()
    self.requested = {c: threading.Event() for c in ('wide', 'narrow')}
    self.last_encoded = {c: float('-inf') for c in self.requested}
    self.latest, self.last_capture, self.issued = {}, {}, OrderedDict()
    self.generation = 0
    self.last_accepted = -1
    self.stream_id = secrets.token_hex(16)
    self._invalid_reason = None
    self.invalidate('starting')

  def invalidate(self, reason):
    if reason == self._invalid_reason:
      return
    self._invalid_reason = reason
    self.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = self.output.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(version=2, valid=False, reason=reason,
                                  updated_mono_ns=max(0, self.last_accepted),
                                  stream_id=self.stream_id, control_eligible=False,
                                  clearance_authorized=False, tracks=[])))
    os.replace(tmp, self.output)

  def reset(self):
    with self.condition:
      self.stream_id = secrets.token_hex(16)
      self.latest.clear()
      self.last_capture.clear()
      self.issued.clear()
      self.last_accepted = -1
      self.generation += 1
      self._invalid_reason = None
      self.invalidate('camera_restarting')
      self.condition.notify_all()

  def claim_capture(self, camera, now, hz):
    if not self.requested[camera].is_set() or now-self.last_encoded[camera] < 1/hz:
      return False
    self.requested[camera].clear()
    self.last_encoded[camera] = now
    return True

  def publish(self, camera, frame):
    with self.condition:
      capture = frame['capture_mono_ns']
      if capture <= self.last_capture.get(camera, -1):
        return
      self.last_capture[camera] = capture
      self.latest[camera] = dict(frame, camera_id=camera)
      self.condition.notify_all()

  def issue(self, timeout=.7):
    started = self.clock()
    with self.condition:
      generation = self.generation
      previous = dict(self.last_capture)
      for event in self.requested.values():
        event.set()
      def ready():
        if generation != self.generation:
          return True
        now = self.clock()
        if set(self.latest) != {'wide', 'narrow'}:
          return False
        w, n = self.latest['wide'], self.latest['narrow']
        if any(f['capture_mono_ns'] <= previous.get(c, -1) or
               not 0 <= now-f['capture_mono_ns'] <= MAX_AGE_NS
               for c, f in self.latest.items()):
          return False
        if abs(w['capture_mono_ns']-n['capture_mono_ns']) > self.max_skew_ns:
          older = 'wide' if w['capture_mono_ns'] < n['capture_mono_ns'] else 'narrow'
          self.requested[older].set()
          return False
        return True
      if not self.condition.wait_for(ready, timeout):
        raise ValueError('dual_camera_unavailable_or_unsynchronized')
      if generation != self.generation:
        raise ValueError('camera_restarting')
      now = self.clock()
      wide, narrow = dict(self.latest['wide']), dict(self.latest['narrow'])
      for f in (wide, narrow):
        f['capture_age_ms'] = (now-f['capture_mono_ns'])/1e6
      pair_id = secrets.token_hex(16)
      identity = tuple((f['frame_id'], f['capture_mono_ns']) for f in (wide, narrow))
      self.issued[pair_id] = identity
      while len(self.issued) > 8:
        self.issued.popitem(last=False)
      return dict(version=2, pair_id=pair_id, stream_id=self.stream_id,
                  wide=wide, narrow=narrow,
                  skew_ms=abs(wide['capture_mono_ns']-narrow['capture_mono_ns'])/1e6,
                  bridge_wait_ms=(now-started)/1e6, control_eligible=False)

  def accept(self, data):
    with self.condition:
      identity = self.issued.pop(data.get('pair_id', ''), None)
      if identity is None or data.get('stream_id') != self.stream_id:
        raise ValueError('unknown_or_replayed_pair')
      if any(type(data.get(c+'_frame_id')) is not int or data[c+'_frame_id'] != identity[i][0]
             for i, c in enumerate(('wide', 'narrow'))):
        raise ValueError('wrong_camera_frame')
      captured = min(i[1] for i in identity)
      if not 0 <= self.clock()-captured <= MAX_AGE_NS or captured <= self.last_accepted:
        raise ValueError('stale_or_out_of_order_result')
      tracks = data.get('tracks')
      if not isinstance(tracks, list) or len(tracks) > 16:
        raise ValueError('invalid_tracks')
      sanitized = []
      for item in tracks:
        if not isinstance(item, dict):
          raise ValueError('invalid_track')
        row = {}
        for k in ('track_id', 'wide_index', 'narrow_index'):
          value = item.get(k)
          if type(value) is not int or not 0 <= value <= 1_000_000:
            raise ValueError('invalid_identity')
          row[k] = value
        for k in ('distance_m', 'relative_speed_mps', 'absolute_speed_mps', 'confidence'):
          value = item.get(k)
          if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError('non_finite_metric')
          if value is not None and ((k == 'distance_m' and not 2 <= value <= 80) or
              (k == 'confidence' and not 0 <= value <= 1) or
              (k.endswith('speed_mps') and abs(value) > 70)):
            raise ValueError('metric_out_of_bounds')
          row[k] = value
        if item.get('distance_source') not in ('dual_ground_estimate', 'unavailable', 'stereo_experimental'):
          raise ValueError('unsupported_distance_source')
        row['distance_source'] = item['distance_source']
        if row['distance_source'] == 'stereo_experimental' and (not self.stereo_sha256 or
            data.get('stereo_calibration_sha256') != self.stereo_sha256):
          raise ValueError('stereo_calibration_not_approved')
        if row['distance_source'] == 'unavailable' and any(row[k] is not None for k in
            ('distance_m', 'relative_speed_mps', 'absolute_speed_mps')):
          raise ValueError('unavailable_metric_present')
        row.update(control_eligible=False, clearance_authorized=False)
        sanitized.append(row)
      result = dict(version=2, source='phone-dual-camera', valid=True,
                    stream_id=self.stream_id, updated_mono_ns=captured,
                    received_mono_ns=self.clock(), tracks=sanitized,
                    stereo_calibrated=any(r['distance_source']=='stereo_experimental' for r in sanitized),
                    stereo_calibration_sha256=self.stereo_sha256,
                    control_eligible=False,
                    clearance_authorized=False, experimental=True)
      tmp = self.output.with_suffix('.tmp')
      tmp.write_text(json.dumps(result, allow_nan=False))
      os.replace(tmp, self.output)
      self.last_accepted = captured
      self._invalid_reason = None
      return result

  def expire(self):
    with self.condition:
      if self.last_accepted < 0 or not 0 <= self.clock()-self.last_accepted <= MAX_AGE_NS:
        self.invalidate('dual_result_unavailable_or_stale')
