"""Pinned navigation-model engine behind the unmodified Jetlink v3 wire.

Navigation is rendered on the Mac and expires there; images and scalar driving
inputs use Jetlink. This module never sends CAN or changes device settings.
"""
import json
import threading
import time

import numpy as np
from jetlink import protocol as P

MODEL_SHA = '1d18c42ea4cd95c8bffab4635844b78b8e2d4e25b9de44a9c5ac2e0961371a2e'
MODEL_REF = 'afbf2e547e9319e2eb9f515e1e4330af63705cec'


class Context:
  def __init__(self):
    self.lock = threading.Lock()
    self.stamp = float('-inf')
    self.image = np.zeros((1, 1, 256, 256), np.float32)
    self.nav = np.zeros((1, 47), np.float32)

  def update(self, image, nav, *, now=None):
    for value, shape in ((image, self.image.shape), (nav, self.nav.shape)):
      if value.shape != shape or value.dtype != np.float32 or not np.isfinite(value).all():
        raise ValueError('Navigation tensor ABI mismatch')
    if np.min(image) < 0 or np.max(image) > 255:
      raise ValueError('Map must use raw grayscale 0..255')
    with self.lock:
      self.image, self.nav = image.copy(), nav.copy()
      self.stamp = time.monotonic() if now is None else now

  def clear(self):
    with self.lock:
      self.stamp = float('-inf')

  def read(self, *, now=None):
    now = time.monotonic() if now is None else now
    with self.lock:
      if not 0 <= now - self.stamp <= 0.5:
        return np.zeros_like(self.image), np.zeros_like(self.nav)
      return self.image.copy(), self.nav.copy()


class Session:
  def __init__(self, engine, context):
    self.engine, self.context = engine, context
    self.greeted = self.ready = False
    self.last_frame = None

  def handle(self, kind, payload):
    if kind == P.Msg.HELLO_REQ:
      json.loads(payload)
      self.engine.reset()
      self.greeted, self.ready, self.last_frame = True, False, None
      return P.Msg.HELLO_RESP, json.dumps({'name': 'Mac official navigation Metal trial',
          'protocol': 3, 'navigation': 'host context, 500ms expiry'}).encode()
    if not self.greeted:
      raise ValueError('HELLO required')
    if kind == P.Msg.ENGINE_REQ:
      request = json.loads(payload)
      spec = self.engine.spec
      self.ready = False
      if request.get('sha256') != MODEL_SHA or request.get('nbytes') != spec.nbytes:
        raise ValueError('Only the pinned official navigation model is installed')
      self.engine.reset()
      self.ready, self.last_frame = True, None
      return P.Msg.ENGINE_RESP, json.dumps({'state': 'ready', 'sha256': spec.sha256,
                                          'spec': spec.to_dict()}).encode()
    if kind == P.Msg.PING:
      return P.Msg.PONG, b''
    if kind == P.Msg.STATE_REQ:
      return P.Msg.STATE_RESP, b'{"backend":"METAL","experimental":true}'
    if kind == P.Msg.SHUTDOWN_REQ:
      self.engine.reset(); self.ready = False
      return P.Msg.SHUTDOWN_RESP, b'{"ok":false,"detail":"Mac power is managed locally"}'
    if kind == P.Msg.LEAVE:
      self.engine.reset(); self.ready = False
      return None
    if kind != P.Msg.INFER_REQ or not self.ready:
      raise ValueError('Engine handshake required or unsupported request')
    spec = self.engine.spec
    if len(payload) != spec.infer_req_nbytes:
      raise ValueError('Frame payload size mismatch')
    frame, flags = P.unpack_infer_req(payload)
    if self.last_frame is not None and not 0 < (frame - self.last_frame) % (1 << 32) < (1 << 31):
      raise ValueError('Repeated or out-of-order frame')
    if flags & P.Flag.RESET_QUEUES:
      self.engine.reset()
    self.last_frame = frame
    start = time.perf_counter()
    feeds = {'new_img': np.frombuffer(payload, np.uint8, spec.warped_nbytes, P.INFER_REQ_SIZE).reshape(spec.warped_shape)}
    scalars = np.frombuffer(payload, '<f4', spec.packed_nelem, P.INFER_REQ_SIZE + spec.warped_nbytes)
    for name, (at, shape) in spec.packed_layout.items():
      feeds[name] = scalars[at].reshape(shape)
    feeds['nav_map'], feeds['navigation'] = self.context.read()
    if not all(np.isfinite(value).all() for value in feeds.values()):
      raise ValueError('Nonfinite model input')
    output = np.asarray(self.engine.run(feeds), dtype='<f4').reshape(-1)
    if output.size != spec.output_nelem or not np.isfinite(output).all():
      raise ValueError('Invalid model output')
    if spec.hidden_range is not None and not flags & P.Flag.WANT_HIDDEN:
      a, b = spec.hidden_range
      output = np.concatenate((output[:a], output[b:]))
    elapsed = min(int((time.perf_counter() - start) * 1e6), (1 << 32) - 1)
    reply = P.pack_infer_resp(frame, 0, elapsed, 0, elapsed) + output.tobytes()
    if flags & P.Flag.WANT_STATE:
      # Pinned Jetlink v3 appends JSON directly, without a length prefix.
      state = b'{"backend":"METAL","experimental":true}'
      reply += state
    return P.Msg.INFER_RESP, reply
