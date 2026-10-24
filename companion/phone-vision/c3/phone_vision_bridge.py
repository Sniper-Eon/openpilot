#!/usr/bin/env python3
"""Wide-camera transport for phone inference. No model or CAN publication.

Results deliberately go to a separate observation file, not side_vehicles.json.
"""
from __future__ import annotations
import argparse
import base64
from collections import OrderedDict
import hmac
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time

MAX_AGE_NS = 800_000_000


def camera_service_name(camera_name, available):
  names = ('wideRoadCameraState',) if camera_name == 'wide' else ('narrowRoadCameraState', 'roadCameraState')
  return next((name for name in names if name in available), None)


def camera_stream_type(camera_name, stream_types):
  names = ('VISION_STREAM_WIDE_ROAD',) if camera_name == 'wide' else ('VISION_STREAM_NARROW_ROAD', 'VISION_STREAM_ROAD')
  for name in names:
    if hasattr(stream_types, name):
      return getattr(stream_types, name)
  raise ValueError('unsupported_camera_stream')


def read_observation(path, now_ns):
  """Read-only observer: process death cannot leave a permanently fresh result."""
  unavailable = {'valid': False, 'status': 'unknown', 'control_eligible': False,
                 'reason': 'missing_malformed_or_stale', 'left': None, 'right': None}
  try:
    with Path(path).open() as f:
      raw = f.read(16_385)
    if len(raw) > 16_384:
      return unavailable
    data = json.loads(raw)
    if not isinstance(data, dict):
      return unavailable
    stamp = data.get('updated_mono_ns')
    if (data.get('valid') is not True or data.get('control_eligible') is not False or
        type(stamp) is not int or not 0 <= now_ns-stamp <= MAX_AGE_NS):
      return unavailable
    return dict(data, status='observation_only')
  except (OSError, ValueError, TypeError):
    return unavailable


class FrameStore:
  def __init__(self, output: Path, clock=time.monotonic_ns):
    self.output, self.clock = output, clock
    self.lock = threading.Lock()
    self.condition = threading.Condition(self.lock)
    self.frame_requested = threading.Event()
    self.last_encoded_at = float("-inf")
    self.last_issued_generation = 0
    self.generation = 0
    self.camera_capture_ns = 0
    self.latest = None
    self.stream_id = secrets.token_hex(16)
    self.issued = OrderedDict()
    self.last_accepted_capture = -1
    self.last_result = None
    self._unavailable_reason = None
    self._invalidate('starting')

  def _persist(self, result):
    self.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = self.output.with_suffix('.tmp')
    tmp.write_text(json.dumps(result, allow_nan=False))
    os.replace(tmp, self.output)

  def _invalidate(self, reason):
    if self._unavailable_reason == reason:
      return
    self._unavailable_reason = reason
    self._persist(dict(version=1, source='tesnav-phone', valid=False,
                       status='unknown', reason=reason, stream_id=self.stream_id,
                       updated_mono_ns=max(0, self.last_accepted_capture),
                       checked_mono_ns=self.clock(), left=None, right=None,
                       experimental=True, control_eligible=False))

  def expire(self):
    with self.lock:
      now = self.clock()
      if not self.camera_capture_ns or not 0 <= now-self.camera_capture_ns <= MAX_AGE_NS:
        self._invalidate('camera_unavailable_or_stale')
      elif self.last_result is None or not 0 <= now-self.last_accepted_capture <= MAX_AGE_NS:
        self._invalidate('phone_result_unavailable_or_stale')

  def claim_capture(self, now, hz):
    if not self.frame_requested.is_set() or now-self.last_encoded_at < 1/hz:
      return False
    self.frame_requested.clear()
    self.last_encoded_at = now
    return True

  def camera_seen(self, capture_ns):
    with self.lock:
      self.camera_capture_ns = capture_ns

  def publish(self, frame):
    with self.condition:
      self.latest = frame
      self.camera_capture_ns = frame['capture_mono_ns']
      self.generation += 1
      self.condition.notify_all()

  def new_stream(self):
    with self.lock:
      self.stream_id = secrets.token_hex(16)
      self.issued.clear()
      self.latest = None
      self.camera_capture_ns = 0
      self.last_result = None
      self._invalidate('camera_restarting')

  def issue(self, fresh=False, timeout=.5, buffered=False):
    started_ns = self.clock()
    with self.condition:
      if fresh:
        generation = self.generation
        # One unused, young prefetch may be delivered immediately. Never serve
        # the same generation twice, or keep streaming JPEGs without requests.
        age = self.clock()-self.latest['capture_mono_ns'] if self.latest is not None else -1
        ready = buffered and self.generation > self.last_issued_generation and 0 <= age <= 150_000_000
        if not ready:
          self.frame_requested.set()
          if not self.condition.wait_for(lambda: self.latest is not None and self.generation > generation, timeout):
            raise ValueError('camera_unavailable_or_stale')
      if self.latest is None or not 0 <= self.clock()-self.latest['capture_mono_ns'] <= MAX_AGE_NS:
        raise ValueError('camera_unavailable_or_stale')
      self.last_issued_generation = self.generation
      if buffered:
        self.frame_requested.set()  # Prepare at most one frame ahead.
      packet = dict(self.latest)
      packet['bridge_wait_ms'] = max(0, (self.clock()-started_ns)/1_000_000)
      packet['capture_age_ms'] = (self.clock()-packet['capture_mono_ns'])/1_000_000
      packet['stream_id'] = self.stream_id
      packet['request_id'] = secrets.token_hex(16)
      self.issued[packet['request_id']] = (packet['capture_mono_ns'], packet['frame_id'])
      while len(self.issued) > 16:
        self.issued.popitem(last=False)
      return packet

  def accept(self, data):
    with self.lock:
      issued = self.issued.pop(data.get('request_id', ''), None)
      if issued is None:
        raise ValueError('unknown_or_replayed_request')
      capture, frame_id = issued
      if not 0 <= self.clock()-capture <= MAX_AGE_NS or capture <= self.last_accepted_capture:
        raise ValueError('stale_or_out_of_order_result')
      if data.get('frame_id') != frame_id:
        raise ValueError('wrong_frame')
      sides = {}
      for side in ('left', 'right'):
        value = data.get(side)
        if value is not None:
          if not isinstance(value, dict):
            raise ValueError('invalid_side')
          for key in ('distance_m', 'relative_speed_mps', 'absolute_speed_mps'):
            x = value.get(key)
            if x is not None and (type(x) not in (int, float) or not math.isfinite(x)):
              raise ValueError('non_finite_metric')
          distance = value.get('distance_m')
          if distance is not None and not 2 <= distance <= 100:
            raise ValueError('distance_out_of_bounds')
          if type(value.get('hits')) is not int or not 1 <= value['hits'] <= 100000:
            raise ValueError('invalid_hits')
          sides[side] = {k: value.get(k) for k in ('track_id', 'distance_m', 'relative_speed_mps', 'absolute_speed_mps', 'hits', 'confidence')}
        else:
          sides[side] = None
      result = dict(version=1, source='tesnav-phone', valid=True,
                    updated_mono_ns=capture, received_mono_ns=self.clock(), frame_id=frame_id, stream_id=self.stream_id,
                    experimental=True, control_eligible=False, **sides)
      self._persist(result)
      self.last_accepted_capture = capture
      self.last_result = result
      self._unavailable_reason = None
      return result


class BridgeServer(ThreadingHTTPServer):
  daemon_threads = True
  def __init__(self, address, token, store, dual_store=None, start_dual=None):
    super().__init__(address, Handler)
    self.token, self.store = token, store
    self.dual_store, self.start_dual = dual_store, start_dual


class Handler(BaseHTTPRequestHandler):
  def log_message(self, *_):
    pass

  def setup(self):
    super().setup()
    self.connection.settimeout(3)

  def respond(self, status, data):
    body = json.dumps(data, allow_nan=False).encode()
    self.send_response(status)
    self.send_header('Content-Type', 'application/json')
    self.send_header('Content-Length', str(len(body)))
    self.send_header('Cache-Control', 'no-store')
    self.end_headers()
    self.wfile.write(body)

  def authorized(self):
    return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+self.server.token)

  def do_GET(self):
    if not self.authorized():
      return self.respond(401, {'error': 'authentication'})
    if self.path == '/v2/pair' and self.server.dual_store is not None:
      try:
        if self.server.start_dual is not None:
          self.server.start_dual()
        return self.respond(200, self.server.dual_store.issue())
      except ValueError as e:
        return self.respond(503, {'error': str(e)})
    if self.path != '/v1/frame':
      return self.respond(404, {'error': 'not_found'})
    try:
      self.respond(200, self.server.store.issue(fresh=True, buffered=True))
    except ValueError as e:
      self.respond(503, {'error': str(e)})

  def do_POST(self):
    if not self.authorized():
      return self.respond(401, {'error': 'authentication'})
    dual = self.path == '/v2/observation' and self.server.dual_store is not None
    if self.path != '/v1/observation' and not dual:
      return self.respond(404, {'error': 'not_found'})
    try:
      length = int(self.headers.get('Content-Length', '0'))
      if not 0 < length <= 8192:
        raise ValueError('body_size')
      data = json.loads(self.rfile.read(length))
      if not isinstance(data, dict):
        raise ValueError('body_type')
      (self.server.dual_store if dual else self.server.store).accept(data)
      self.respond(200, {'accepted': True, 'control_eligible': False})
    except (ValueError, TypeError) as e:
      self.respond(400, {'error': str(e)})


def camera_frames(make_client, clock=time.monotonic, sleep=time.sleep):
  """Recreate IPC mappings after camerad restarts or stops producing frames."""
  client = None
  last_frame = clock()
  while True:
    if client is None:
      client = make_client()
      if not client.connect(False):
        client = None
        sleep(.5)
        continue
      last_frame = clock()
    try:
      buf = client.recv(timeout_ms=100)
    except (RuntimeError, ConnectionError):
      client = None
      sleep(.5)
      continue
    if buf is None:
      if clock() - last_frame >= 2:
        client = None
      sleep(.02)
      continue
    last_frame = clock()
    yield client, buf


def output_frame_size(width, height, max_width=960):
  if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
    raise ValueError('invalid camera dimensions')
  if max_width not in (0, 960, 1280, 1928):
    raise ValueError('unsupported frame width')
  # No camera reconfiguration or upscaling; change only the transport image.
  scale = min(1., (max_width or 1928)/width, 1208/height)
  return max(1, round(width*scale)), max(1, round(height*scale))


def capture(store, roi_path, hz, max_width=960, jpeg_quality=75, camera_name='wide', dual_store=None):
  import cv2
  import numpy as np
  from msgq.visionipc import VisionIpcClient
  from openpilot.cereal.visionipc import VisionStreamType
  from openpilot.cereal import messaging
  from openpilot.cereal.services import SERVICE_LIST
  from openpilot.common.transformations.camera import DEVICE_CAMERAS, get_view_frame_from_calib_frame, view_frame_from_device_frame
  from openpilot.common.transformations.orientation import rot_from_euler
  cv2.setNumThreads(1)
  roi = json.loads(Path(roi_path).read_text())
  camera_service = camera_service_name(camera_name, SERVICE_LIST)
  if camera_service is None:
    raise ValueError('camera_metadata_service_missing')
  stream = camera_stream_type(camera_name, VisionStreamType)
  sm = messaging.SubMaster(['deviceState', 'carState', 'extrinsicsCalibration', camera_service])
  make_client = lambda: VisionIpcClient('camerad', stream, conflate=True)
  previous_client = None
  last_encoded = float('-inf')
  try:
    device_id = hashlib.sha256(Path('/etc/machine-id').read_bytes().strip()).hexdigest()[:24]
  except OSError:
    device_id = None
  for client, buf in camera_frames(make_client):
    if client is not previous_client:
      if camera_name == 'wide':
        store.new_stream()
      if dual_store is not None:
        dual_store.reset()
      previous_client = client
    started = time.monotonic()
    capture_ns = int(client.timestamp_eof)
    if not 0 <= time.monotonic_ns()-capture_ns <= MAX_AGE_NS:
      continue
    if camera_name == 'wide':
      store.camera_seen(capture_ns)
    # Native IPC is conflated: drain cheaply, encode only when a phone asks.
    # Never accumulate a queue; hz is a hard maximum for JPEG work.
    if started-last_encoded < 1/hz:
      continue
    single_requested = camera_name == 'wide' and store.claim_capture(started, hz)
    dual_requested = dual_store is not None and dual_store.claim_capture(camera_name, started, hz)
    if not single_requested and not dual_requested:
      continue
    last_encoded = started
    sm.update(0)
    # Copy before the next recv: camera buffers belong to vision IPC.
    raw = np.frombuffer(buf.data, dtype=np.uint8)
    w, h, stride = int(buf.width), int(buf.height), int(buf.stride)
    y = raw[:stride*h].reshape(h, stride)[:, :w]
    uv = raw[int(buf.uv_offset):int(buf.uv_offset)+stride*(h//2)].reshape(h//2, stride)[:, :w]
    bgr = cv2.cvtColor(np.vstack((y, uv)), cv2.COLOR_YUV2BGR_NV12)
    width, height = output_frame_size(w, h, max_width)
    if (width, height) != (w, h):
      bgr = cv2.resize(bgr, (width, height), interpolation=cv2.INTER_AREA)
    inv, intrinsics, view_rotation, calibration_id, view_from_calib = None, None, None, None, None
    try:
      camera_fresh = all(sm.seen[s] and sm.alive[s] and sm.valid[s] for s in (camera_service, 'deviceState'))
      if not camera_fresh:
        raise ValueError('camera profile unavailable')
      configs = DEVICE_CAMERAS[(str(sm['deviceState'].deviceType), str(sm[camera_service].sensor))]
      camera = configs.wide_road if camera_name == 'wide' else configs.narrow_road
      if (w, h) != (camera.width, camera.height):
        raise ValueError('source camera geometry changed')
      k = camera.intrinsics.copy().astype(float)
      k[0] *= width/camera.width
      k[1] *= height/camera.height
      intrinsics = k.reshape(-1).tolist()
      # Intrinsic/profile identity is available during parked calibration even
      # when the onroad live ground-pose producer is intentionally not running.
      profile = [camera_name, str(sm['deviceState'].deviceType), str(sm[camera_service].sensor),
                 w, h, width, height, camera.focal_length]
      calibration_id = hashlib.sha256(json.dumps(profile).encode()).hexdigest()[:24]
      cal = sm['extrinsicsCalibration']
      fresh = all(sm.seen[s] and sm.alive[s] and sm.valid[s] for s in ('extrinsicsCalibration', camera_service, 'deviceState'))
      age = time.monotonic_ns()-sm.logMonoTime['extrinsicsCalibration']
      if fresh and 0 <= age <= 2_000_000_000 and str(cal.calStatus) == 'calibrated' and len(cal.height) and .5 <= cal.height[0] <= 3:
        view = get_view_frame_from_calib_frame(*cal.rpyCalib, float(cal.height[0]))
        rotation = (view_frame_from_device_frame @ rot_from_euler(cal.wideFromDeviceEuler) @ view_frame_from_device_frame.T
                    if camera_name == 'wide' else np.eye(3))
        projection = k @ rotation @ view
        inverse = np.linalg.inv(projection[:, [0, 1, 3]])
        if not np.isfinite(inverse).all():
          raise ValueError('invalid ground projection')
        inv = inverse.reshape(-1).tolist()
        intrinsics = k.reshape(-1).tolist()
        view_rotation = rotation.reshape(-1).tolist()
        view_from_calib = (rotation @ view).reshape(-1).tolist()
    except (KeyError, ValueError, np.linalg.LinAlgError):
      pass
    ok, jpg = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    if ok:
      car_fresh = sm.seen['carState'] and sm.alive['carState'] and sm.valid['carState'] and 0 <= time.monotonic_ns()-sm.logMonoTime['carState'] <= 250_000_000
      speed = float(sm['carState'].vEgo) if car_fresh else None
      speed = speed if speed is not None and math.isfinite(speed) else None
      packet = dict(version=1, frame_id=int(client.frame_id), capture_mono_ns=capture_ns,
                         width=width, height=height, jpeg_b64=base64.b64encode(jpg).decode(),
                         ego_speed_mps=speed,
                         ground_inverse=inv, roi=roi, jpeg_bytes=len(jpg),
                         bridge_processing_ms=(time.monotonic()-started)*1000,
                         camera_id=camera_name, calibration_id=calibration_id, device_id=device_id,
                         camera_matrix=intrinsics, view_rotation=view_rotation,
                         view_from_calib=view_from_calib,
                         source_width=w, source_height=h, stereo_calibrated=False)
      if single_requested:
        store.publish(packet)
      if dual_requested:
        dual_store.publish(camera_name, packet)


def main():
  p = argparse.ArgumentParser()
  p.add_argument('--bind', default='0.0.0.0')
  p.add_argument('--port', type=int, default=8767)
  p.add_argument('--token-file', type=Path, required=True)
  p.add_argument('--roi', default='/data/wide-capture/roi.json')
  p.add_argument('--hz', type=float, default=5)
  p.add_argument('--frame-width', type=int, choices=(0, 960, 1280, 1928), default=960, help='0 keeps source dimensions within 1928x1208; no upscaling')
  p.add_argument('--jpeg-quality', type=int, choices=range(75, 96), default=75)
  p.add_argument('--output', type=Path, default=Path('/dev/shm/phone_side_vehicles.json'))
  p.add_argument('--dual-camera', action='store_true', help='enable separate read-only /v2 endpoints; narrow capture starts on demand')
  p.add_argument('--dual-output', type=Path, default=Path('/dev/shm/phone_dual_vehicles.json'))
  p.add_argument('--stereo-calibration', type=Path, help='optional identical validated calibration file approved on C3 and phone')
  args = p.parse_args()
  if args.stereo_calibration and not args.dual_camera:
    p.error('stereo calibration requires --dual-camera')
  if not math.isfinite(args.hz) or not 2 <= args.hz <= 10:
    p.error('hz must be 2..10 (maximum on-demand encode rate)')
  token = args.token_file.read_text().strip()
  if len(token) < 32:
    p.error('connection code must have at least 32 characters')
  store = FrameStore(args.output)
  dual = None
  if args.dual_camera:
    from dual_camera_store import DualCameraStore
    if args.dual_output == args.output:
      p.error('dual output must be separate from legacy observation')
    calibration_sha = None
    if args.stereo_calibration:
      raw = args.stereo_calibration.read_bytes()
      if not 0 < len(raw) <= 65_536:
        p.error('invalid stereo calibration file size')
      calibration = json.loads(raw)
      if (calibration.get('validated') is not True or calibration.get('units') != 'metres' or
          calibration.get('calibration_pairs', 0) < 15 or calibration.get('validation_pairs', 0) < 5 or
          any(type(calibration.get(k)) not in (int, float) or not 0 <= calibration[k] <= 1
              for k in ('stereo_rms_px', 'heldout_rms_px'))):
        p.error('stereo calibration did not pass quality gates')
      calibration_sha = hashlib.sha256(raw).hexdigest()
    dual = DualCameraStore(args.dual_output, stereo_sha256=calibration_sha)
  def watchdog():
    while True:
      store.expire()
      if dual is not None:
        dual.expire()
      time.sleep(.2)
  threading.Thread(target=watchdog, daemon=True).start()
  def capture_worker(camera_name, hz):
    while True:
      try:
        capture(store, args.roi, hz, args.frame_width, args.jpeg_quality, camera_name, dual)
      except Exception as error:
        if camera_name == 'wide':
          store.new_stream()
        if dual is not None:
          dual.reset()
        print(f'{camera_name} capture restarting: {type(error).__name__}', flush=True)
        time.sleep(1)
  threading.Thread(target=capture_worker, args=('wide', args.hz), daemon=True).start()
  narrow_lock, narrow_started = threading.Lock(), [False]
  def start_dual():
    with narrow_lock:
      if not narrow_started[0]:
        threading.Thread(target=capture_worker, args=('narrow', min(args.hz, 4)), daemon=True).start()
        narrow_started[0] = True
  with BridgeServer((args.bind, args.port), token, store, dual, start_dual) as server:
    server.serve_forever()


if __name__ == '__main__':
  main()
