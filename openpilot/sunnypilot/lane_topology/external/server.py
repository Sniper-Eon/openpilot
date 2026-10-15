"""Authenticated, single-request offboard observer. Run on the Mac, not Comma."""
from __future__ import annotations

import argparse
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time

import cv2
import numpy as np

from openpilot.sunnypilot.lane_topology.external.perception import YOLOPv2
from openpilot.sunnypilot.lane_topology.external.discovery import DiscoveryResponder
from openpilot.sunnypilot.lane_topology.external.protocol import MAX_BODY, validate_frame


class LaneServer(ThreadingHTTPServer):
  allow_reuse_address = True

  def __init__(self, address, model, token: str):
    if len(token) < 32:
      raise ValueError('a private token of at least 32 characters is required')
    self.model, self.token = model, token
    self.client_slots = threading.BoundedSemaphore(8)
    self.model_lock = threading.Lock()
    self.last_result = None
    self.count = 0
    self.started = time.monotonic()
    super().__init__(address, Handler)
    self.timeout = 1


  def process_request(self, request, client_address):
    if not self.client_slots.acquire(blocking=False):
      self.shutdown_request(request)
      return
    try:
      super().process_request(request, client_address)
    except BaseException:
      self.client_slots.release()
      raise

  def process_request_thread(self, request, client_address):
    try:
      super().process_request_thread(request, client_address)
    finally:
      self.client_slots.release()


class Handler(BaseHTTPRequestHandler):
  def setup(self):
    super().setup()
    self.connection.settimeout(2)

  def log_message(self, *_args):
    pass

  def respond(self, code: int, value: dict):
    body = json.dumps(value, allow_nan=False).encode()
    self.send_response(code)
    self.send_header('Content-Type', 'application/json')
    self.send_header('Content-Length', str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def do_GET(self):
    if self.path != '/health':
      self.respond(404, {'error': 'notFound'})
      return
    self.respond(200, {'ready': True, 'display_only': True, 'frames': self.server.count,
                       'last_inference_ms': (self.server.last_result or {}).get('inference_ms')})

  def do_POST(self):
    if self.path != '/infer':
      self.respond(404, {'error': 'notFound'})
      return
    if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token):
      self.respond(401, {'error': 'unauthorized'})
      return
    if not self.server.model_lock.acquire(blocking=False):
      self.respond(429, {'error': 'busy'})
      return
    try:
      size = int(self.headers.get('Content-Length', '0'))
      if not 0 < size <= MAX_BODY:
        raise ValueError('oversized request')
      value = json.loads(self.rfile.read(size))
      validate_frame(value)
      image_bytes = base64.b64decode(value['jpeg'], validate=True)
      # Verify dimensions before allocation/decode, including decompression bombs.
      from PIL import Image
      import io
      with Image.open(io.BytesIO(image_bytes)) as header:
        if header.format != 'JPEG' or not (32 <= header.width <= 1280 and 32 <= header.height <= 960):
          raise ValueError('invalid JPEG dimensions')
      image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
      if image is None:
        raise ValueError('invalid JPEG')
      result = self.server.model.infer(image, value)
      self.server.last_result = result
      self.server.count += 1
      self.respond(200, result)
    except (ValueError, TypeError, KeyError, OSError):
      self.respond(400, {'error': 'invalidFrame'})
    except Exception:
      self.respond(503, {'error': 'inferenceUnavailable'})
    finally:
      self.server.model_lock.release()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--weights', required=True)
  parser.add_argument('--token-file', required=True)
  parser.add_argument('--bind', default='127.0.0.1')
  parser.add_argument('--port', type=int, default=7788)
  parser.add_argument('--device', choices=('cpu', 'mps'), default='cpu')
  parser.add_argument('--threads', type=int, choices=range(1, 5), default=2)
  args = parser.parse_args()
  os.nice(10)
  model = YOLOPv2(args.weights, device=args.device, threads=args.threads)
  # Warm up before accepting a camera connection; startup cost is not a frame.
  model.infer(np.zeros((384, 640, 3), np.uint8), {
    'version': 1, 'session': '0'*32, 'sequence': 1, 'frame_id': 0,
    'capture_mono_ns': 1, 'ego_point': [0.5, 0.7], 'camera': 'wideRoad',
  })
  token = Path(args.token_file).read_text().strip()
  with LaneServer((args.bind, args.port), model, token) as server, DiscoveryResponder(token, server.server_port, bind=args.bind):
    print(f'External lane observer ready on {args.bind}:{args.port}; display only', flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == '__main__':
  main()
