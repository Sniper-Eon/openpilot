"""One low-rate wide frame at a time; no driving inference or CAN access."""
from __future__ import annotations

import base64
import ipaddress
import json
import math
import re
from pathlib import Path
import time
import uuid
import zlib
from urllib.parse import urlparse

import numpy as np
import requests

from openpilot.sunnypilot.lane_topology.external.discovery import discover

from openpilot.sunnypilot.lane_topology.external.protocol import (
  CONFIG_PATH, MAX_RESPONSE, RESULT_PATH, validate_frame, validate_result,
)


def load_config(path: Path = CONFIG_PATH) -> dict | None:
  if not path.exists():
    return None
  if path.stat().st_size > 4096:
    raise ValueError('oversized configuration')
  value = json.loads(path.read_text())
  url = urlparse(value['url'])
  if url.scheme != 'http' or url.path not in ('', '/') or url.username or url.password or url.query or url.fragment:
    raise ValueError('expected a private HTTP host URL')
  host = url.hostname or ''
  if not re.fullmatch(r'[A-Za-z0-9-]{1,63}\.local', host):
    ip = ipaddress.ip_address(host)
    if not (ip.is_private or ip.is_loopback) or ip.is_unspecified or ip.is_multicast:
      raise ValueError('host must be a private IP or local mDNS name')
  if not isinstance(value['token'], str) or len(value['token']) < 32:
    raise ValueError('missing pairing token')
  if 'discovery' in value and type(value['discovery']) is not bool:
    raise ValueError('discovery must be a switch')
  return value


def export_nv12(frame) -> dict:
  width, height, stride, uv_offset = int(frame.width), int(frame.height), int(frame.stride), int(frame.uv_offset)
  if width % 2 or height % 2 or not (32 <= width <= 3840 and 32 <= height <= 2160) or stride < width or uv_offset < stride*height:
    raise ValueError('invalid NV12 frame')
  data = np.frombuffer(frame.data, dtype=np.uint8)
  if len(data) < uv_offset + stride*(height//2):
    raise ValueError('truncated NV12 frame')
  y = data[:stride*height].reshape(height, stride)[:, :width]
  uv = data[uv_offset:uv_offset + stride*(height//2)].reshape(height//2, stride)[:, :width].reshape(height//2, width//2, 2)
  scale = min(640/width, 480/height, 1.0)
  tw, th = int(width*scale)//2*2, int(height*scale)//2*2
  if tw < 32 or th < 32:
    raise ValueError('unsupported camera aspect ratio')
  xs = np.linspace(0, width-1, tw).astype(np.int32)
  ys = np.linspace(0, height-1, th).astype(np.int32)
  # Keep the chroma samples aligned with the corresponding sampled Y blocks.
  small_y = y[ys[:,None], xs[None,:]]
  small_uv = uv[(ys[::2]//2)[:,None], (xs[::2]//2)[None,:]]
  raw = small_y.tobytes() + small_uv.tobytes()
  return {'nv12_zlib': base64.b64encode(zlib.compress(raw,1)).decode(), 'width': tw, 'height': th}


def request_result(config: dict, frame: dict, image: bytes | dict, *, session=None, now_ns=None) -> dict:
  validate_frame(frame)
  payload = {'jpeg': base64.b64encode(image).decode()} if isinstance(image, bytes) else image
  if not isinstance(payload, dict) or set(payload) not in ({'jpeg'}, {'nv12', 'width', 'height'}, {'nv12_zlib', 'width', 'height'}):
    raise ValueError('invalid image payload')
  client = session or requests.Session()
  if session is None:
    client.trust_env = False
  try:
    with client.post(config['url'].rstrip('/') + '/infer',
                     json={**frame, **payload},
                     headers={'Authorization': 'Bearer ' + config['token']},
                     timeout=(1.0, 1.0), allow_redirects=False, stream=True) as response:
      if response.status_code != 200:
        raise ValueError(f'host returned {response.status_code}')
      data = bytearray()
      for chunk in response.iter_content(4096):
        data.extend(chunk)
        if len(data) > MAX_RESPONSE:
          raise ValueError('oversized response')
      return validate_result(json.loads(data), frame, now_ns=time.monotonic_ns() if now_ns is None else now_ns)
  finally:
    if session is None:
      client.close()



STATUS_PATH = RESULT_PATH.with_name('external_lane_status.json')


def resolve_endpoint(config: dict, previous: str | None = None) -> str | None:
  if not config.get('discovery'):
    return config['url']
  # Reauthenticate the last discovered address before relying on lossy broadcasts.
  if previous:
    endpoint = discover(config['token'], target=urlparse(previous).hostname)
    if endpoint:
      return endpoint
  endpoint = discover(config['token'])
  if endpoint:
    return endpoint
  configured = urlparse(config['url']).hostname
  if not previous or configured != urlparse(previous).hostname:
    return discover(config['token'], target=configured)
  return None


def failure_reason(error: Exception) -> str:
  # Do not persist arbitrary exception text: requests errors can contain URLs.
  known = {'paired host not found', 'wide camera unavailable', 'camera frame is stale',
           'expired frame', 'response does not match outstanding frame',
           'missing calibrated ego point', 'invalid NV12 frame', 'truncated NV12 frame',
           'host returned 400', 'host returned 401', 'host returned 429', 'host returned 503'}
  text = str(error)
  return text if text in known else type(error).__name__


def write_status(state: str, *, reason: str, stable: int = 0, total_ms: float = 0.0):
  from openpilot.sunnypilot.navassist.settings import atomic_json
  atomic_json(STATUS_PATH, {'version': 1, 'updated_mono_ns': time.monotonic_ns(),
                           'state': state, 'reason': reason, 'stable_samples': stable,
                           'total_ms': round(total_ms, 2)})


class StableObservation:
  def __init__(self):
    self.reset()

  def reset(self):
    self.key = None
    self.count = 0

  def update(self, result: dict) -> dict:
    if not result['valid']:
      self.reset()
      return result
    key = (result['visible_lane_count'], result['ego_lane_index'])
    self.count = self.count + 1 if key == self.key else 1
    self.key = key
    if self.count < 3:
      return result | dict(valid=False, visible_lane_count=0, ego_lane_index=-1,
                           score=0, reason='stabilizing')
    return result


def calibrated_ego_point(sm) -> list[float] | None:
  from openpilot.cereal import log
  from openpilot.common.transformations.camera import DEVICE_CAMERAS, view_frame_from_device_frame
  from openpilot.common.transformations.orientation import rot_from_euler
  services = ('extrinsicsCalibration', 'deviceState', 'wideRoadCameraState')
  if not all(sm.seen[s] and sm.alive[s] and sm.valid[s] for s in services):
    return None
  calibration = sm['extrinsicsCalibration']
  if calibration.calStatus != log.ExtrinsicsCalibration.Status.calibrated or len(calibration.rpyCalib) != 3 or len(calibration.wideFromDeviceEuler) != 3:
    return None
  try:
    camera = DEVICE_CAMERAS[(str(sm['deviceState'].deviceType), str(sm['wideRoadCameraState'].sensor))].wide_road
    rotation = view_frame_from_device_frame @ rot_from_euler(calibration.wideFromDeviceEuler) @ rot_from_euler(calibration.rpyCalib)
    heights = [float(v) for v in calibration.height if np.isfinite(v) and 0.5 <= v <= 3.0]
    if not heights:
      for line in tuple(sm['modelV2'].laneLines)[1:3]:
        if len(line.x) >= 2 and len(line.x) == len(line.z) and line.x[0] <= 10 <= line.x[len(line.x)-1]:
          height = float(np.interp(10.0, list(line.x), list(line.z)))
          if np.isfinite(height) and 0.5 <= height <= 3.0:
            heights.append(height)
    if not heights:
      return None
    point = camera.intrinsics @ rotation @ np.array([10.0, 0.0, float(np.median(heights))])
    if point[2] <= 0:
      return None
    x, y = point[:2] / point[2] / np.array([camera.width, camera.height])
    return [float(x), float(y)] if 0.1 <= x <= 0.9 and 0.45 <= y <= 0.95 else None
  except (KeyError, ValueError):
    return None


def primary_has_budget(primary) -> bool:
  execution, dropped = float(primary.modelExecutionTime), float(primary.frameDropPerc)
  return math.isfinite(execution) and math.isfinite(dropped) and 0 <= execution <= 0.045 and 0 <= dropped <= 5


def main():
  from msgq.visionipc import VisionIpcClient
  from openpilot.cereal import messaging
  from openpilot.cereal.visionipc import VisionStreamType
  from openpilot.sunnypilot.navassist.settings import atomic_json
  from openpilot.common.swaglog import cloudlog
  from openpilot.common.params import Params
  config = load_config()
  if config is None:
    return
  client = VisionIpcClient('camerad', VisionStreamType.VISION_STREAM_WIDE_ROAD, conflate=True)
  sm = messaging.SubMaster(['extrinsicsCalibration', 'deviceState', 'wideRoadCameraState', 'modelV2'])
  session_id, sequence = uuid.uuid4().hex, 0
  stability = StableObservation()
  connected = False
  endpoint = None
  params = Params()
  with requests.Session() as http:
    http.trust_env = False
    while True:
      started = time.monotonic()
      try:
        if not connected:
          connected = client.connect(False)
          if not connected:
            write_status('waiting', reason='wide camera unavailable')
            time.sleep(1)
            continue
        sm.update(0)
        ego = calibrated_ego_point(sm)
        # No export when the original driving inference is unhealthy/over budget.
        healthy = sm.seen['modelV2'] and sm.alive['modelV2'] and sm.valid['modelV2']
        primary = sm['modelV2']
        if (params.get_bool('IsOffroad') or ego is None or not healthy or
            not primary_has_budget(primary)):
          stability.reset()
          RESULT_PATH.unlink(missing_ok=True)
          reason = ('offroad' if params.get_bool('IsOffroad') else 'calibration unavailable' if ego is None
                    else 'primary unavailable' if not healthy else 'primary over budget')
          write_status('waiting', reason=reason)
          time.sleep(0.5)
          continue
        # Discover before receiving a fresh frame, so network lookup cannot age it.
        resolved = resolve_endpoint(config, endpoint)
        if resolved is None:
          raise ValueError('paired host not found')
        endpoint = resolved
        camera = client.recv(timeout_ms=100)
        if camera is None:
          connected = False
          client = VisionIpcClient('camerad', VisionStreamType.VISION_STREAM_WIDE_ROAD, conflate=True)
          raise ValueError('wide camera unavailable')
        captured = int(client.timestamp_eof)
        if not 0 <= time.monotonic_ns() - captured <= 250_000_000:
          raise ValueError('camera frame is stale')
        sequence += 1
        frame = {'version': 1, 'session': session_id, 'sequence': sequence,
                 'frame_id': int(client.frame_id), 'capture_mono_ns': captured,
                 'ego_point': ego, 'camera': 'wideRoad'}
        result = request_result(config | {'url': endpoint}, frame, export_nv12(camera), session=http)
        result = stability.update(result)
        atomic_json(RESULT_PATH, result)
        write_status('valid' if result['valid'] else 'waiting', reason=result['reason'],
                     stable=stability.count, total_ms=(time.monotonic()-started)*1000)
      except (ValueError, OSError, requests.RequestException ) as error:
        stability.reset()
        RESULT_PATH.unlink(missing_ok=True)
        reason = failure_reason(error)
        write_status('error', reason=reason, total_ms=(time.monotonic()-started)*1000)
        cloudlog.warning('external lane observation unavailable: %s', reason)
      # At most one frame per second, with no background queue or retry backlog.
      time.sleep(max(0.05, 1.0 - (time.monotonic() - started)))


if __name__ == '__main__':
  main()
