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
from urllib.parse import urlparse

import cv2
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
  return value


def encode_nv12(frame) -> bytes:
  width, height, stride, uv_offset = int(frame.width), int(frame.height), int(frame.stride), int(frame.uv_offset)
  if width % 2 or height % 2 or not (32 <= width <= 3840 and 32 <= height <= 2160) or stride < width or uv_offset < stride*height:
    raise ValueError('invalid NV12 frame')
  data = np.frombuffer(frame.data, dtype=np.uint8)
  if len(data) < uv_offset + stride*(height//2):
    raise ValueError('truncated NV12 frame')
  y = data[:stride*height].reshape(height, stride)[:, :width]
  uv = data[uv_offset:uv_offset + stride*(height//2)].reshape(height//2, stride)[:, :width].reshape(height//2, width//2, 2)
  # Downsample before color conversion/JPEG to bound the device cost.
  target_w = min(960, width)
  target_w -= target_w % 2
  target_h = max(32, round(height * target_w / width))
  target_h -= target_h % 2
  y = cv2.resize(y, (target_w, target_h), interpolation=cv2.INTER_AREA)
  uv = cv2.resize(uv, (target_w//2, target_h//2), interpolation=cv2.INTER_AREA)
  bgr = cv2.cvtColorTwoPlane(y, uv, cv2.COLOR_YUV2BGR_NV12)
  ok, jpeg = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
  if not ok or jpeg.nbytes > 250_000:
    raise ValueError('JPEG size out of range')
  return jpeg.tobytes()


def request_result(config: dict, frame: dict, jpeg: bytes, *, session=None, now_ns=None) -> dict:
  validate_frame(frame)
  client = session or requests.Session()
  if session is None:
    client.trust_env = False
  try:
    with client.post(config['url'].rstrip('/') + '/infer',
                     json={**frame, 'jpeg': base64.b64encode(jpeg).decode()},
                     headers={'Authorization': 'Bearer ' + config['token']},
                     timeout=(0.25, 1.0), allow_redirects=False, stream=True) as response:
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
  cv2.setNumThreads(1)
  config = load_config()
  if config is None:
    return
  client = VisionIpcClient('camerad', VisionStreamType.VISION_STREAM_WIDE_ROAD, conflate=True)
  sm = messaging.SubMaster(['extrinsicsCalibration', 'deviceState', 'wideRoadCameraState', 'modelV2'])
  session_id, sequence = uuid.uuid4().hex, 0
  last_index, stable = None, 0
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
            time.sleep(1)
            continue
        sm.update(0)
        ego = calibrated_ego_point(sm)
        # No export when the original driving inference is unhealthy/over budget.
        healthy = sm.seen['modelV2'] and sm.alive['modelV2'] and sm.valid['modelV2']
        primary = sm['modelV2']
        if (params.get_bool('IsOffroad') or ego is None or not healthy or
            not primary_has_budget(primary)):
          last_index, stable = None, 0
          RESULT_PATH.unlink(missing_ok=True)
          time.sleep(0.5)
          continue
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
        if config.get('discovery'):
          endpoint = discover(config['token'])
          if endpoint is None:
            raise ValueError('paired host not found')
        else:
          endpoint = config['url']
        result = request_result(config | {'url': endpoint}, frame, encode_nv12(camera), session=http)
        key = (result['visible_lane_count'], result['ego_lane_index']) if result['valid'] else None
        stable = stable + 1 if key is not None and key == last_index else 1
        last_index = key
        if stable < 3 or key is None:
          result.update(valid=False, visible_lane_count=0, ego_lane_index=-1, score=0, reason='stabilizing')
        atomic_json(RESULT_PATH, result)
      except (ValueError, OSError, requests.RequestException, cv2.error) as error:
        endpoint = None
        last_index, stable = None, 0
        RESULT_PATH.unlink(missing_ok=True)
        cloudlog.warning('external lane observation unavailable: %s', type(error).__name__)
      # At most one frame per second, with no background queue or retry backlog.
      time.sleep(max(0.05, 1.0 - (time.monotonic() - started)))


if __name__ == '__main__':
  main()
