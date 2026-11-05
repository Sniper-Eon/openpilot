"""Failures: stale/future/malformed nav, wrong model, inference before handshake,
bad frame sizes, replayed frame IDs, nonfinite output, leaked recurrent state.
Tests are CPU-only; the separate parity runner exercises real Metal inference.
"""
import unittest
import numpy as np
from jetlink import protocol as P
from tools.nav_bigmodel.session import Context, Session, MODEL_SHA
from jetlink.spec import ModelSpec


class FakeEngine:
  spec = ModelSpec(MODEL_SHA, 814591106, 4,
                   {'new_img': (2, 6, 128, 256), 'desire': (8,), 'traffic_convention': (1, 2),
                    'action_t': (1, 2), 'nav_map': (1, 1, 256, 256), 'navigation': (1, 47)},
                   {'outputs': (1, 4)}, {}, None)

  def __init__(self):
    self.resets = 0
    self.calls = []

  def reset(self):
    self.resets += 1

  def run(self, feeds):
    self.calls.append(feeds)
    return np.zeros(4, np.float32)


class Contract(unittest.TestCase):
  def test_real_client_reconnect_and_fault(self):
    import threading
    from jetlink.client import JetlinkClient
    from jetlink.transport.tcp import TcpTransport
    from jetlink.transport.base import LinkError
    from tools.nav_bigmodel.serve import serve
    listener = TcpTransport.listen('127.0.0.1', 0)
    engine = FakeEngine()
    def worker():
      for _ in range(2):
        try:
          transport, _ = TcpTransport.accept(listener)
          serve(transport, engine, Context())
        except LinkError:
          pass
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    client = JetlinkClient.open_tcp('127.0.0.1', listener.getsockname()[1])
    try:
      client.hello()
      with self.assertRaises(LinkError): client.ensure_engine('wrong', 814591106)
      client.hello()
      spec = client.ensure_engine(MODEL_SHA, 814591106)
      image = np.zeros(spec.warped_shape, np.uint8)
      packed = np.zeros(spec.packed_nelem, np.float32)
      result = client.infer(image, packed, frame_id=1, reset=True, want_state=True)
      self.assertEqual(result.shape, (4,))
      self.assertEqual(client.last_state['backend'], 'METAL')
      packed[0] = np.nan
      with self.assertRaises(LinkError): client.infer(image, packed, frame_id=2)
      client.close()
      client = JetlinkClient.open_tcp('127.0.0.1', listener.getsockname()[1])
      client.hello()
      client.ensure_engine(MODEL_SHA, 814591106)
      packed[:] = 0
      self.assertTrue(np.isfinite(client.infer(image, packed, frame_id=1)).all())
    finally:
      client.close(); listener.close(); thread.join(timeout=2)
    self.assertFalse(thread.is_alive())

  def test_context(self):
    c = Context()
    image, nav = np.ones((1, 1, 256, 256), np.float32), np.ones((1, 47), np.float32)
    c.update(image, nav, now=10)
    self.assertTrue(c.read(now=10.1)[0].any())
    self.assertFalse(c.read(now=10.6)[0].any())
    self.assertFalse(c.read(now=9)[0].any())
    with self.assertRaises(ValueError): c.update(image * np.nan, nav)
    with self.assertRaises(ValueError): c.update(image[:,:,:,:1], nav)

  def test_handshake_and_frames(self):
    e = FakeEngine(); s = Session(e, Context())
    with self.assertRaises(ValueError): s.handle(P.Msg.INFER_REQ, b'')
    s.handle(P.Msg.HELLO_REQ, b'{}')
    with self.assertRaises(ValueError): s.handle(P.Msg.ENGINE_REQ, b'{"sha256":"wrong"}')
    import json
    s.handle(P.Msg.ENGINE_REQ, json.dumps({'sha256': MODEL_SHA, 'nbytes': 814591106}).encode())
    with self.assertRaises(ValueError): s.handle(P.Msg.INFER_REQ, b'bad')
    body = P.pack_infer_req(1, P.Flag.RESET_QUEUES) + bytes(e.spec.warped_nbytes + e.spec.packed_nbytes)
    kind, reply = s.handle(P.Msg.INFER_REQ, body)
    self.assertEqual(kind, P.Msg.INFER_RESP)
    self.assertEqual(P.unpack_infer_resp(reply)[0:2], (1, 0))
    self.assertFalse(e.calls[-1]['nav_map'].any())
    with self.assertRaises(ValueError): s.handle(P.Msg.INFER_REQ, body)
    before = e.resets; s.handle(P.Msg.HELLO_REQ, b'{}'); self.assertGreater(e.resets, before)

  def test_nonfinite_output(self):
    import json
    e = FakeEngine(); e.run = lambda feeds: np.full(4, np.nan, np.float32)
    s = Session(e, Context()); s.handle(P.Msg.HELLO_REQ, b'{}')
    s.handle(P.Msg.ENGINE_REQ, json.dumps({'sha256': MODEL_SHA, 'nbytes': 814591106}).encode())
    with self.assertRaises(ValueError):
      s.handle(P.Msg.INFER_REQ, P.pack_infer_req(1) + bytes(e.spec.warped_nbytes + e.spec.packed_nbytes))


if __name__ == '__main__': unittest.main()
