"""Failures: disabled route intake, missing owner, wrong revision, bad hash,
geometry renewing snapshot TTL, and cached geometry surviving master disable.
Uses the real UDP receiver and the existing phone chunk protocol.
"""
import base64
import hashlib
import json
import threading
import time
import unittest

from openpilot.sunnypilot.navassist.protocol import NavAssistStore
from openpilot.sunnypilot.navassist.tests.test_protocol import SOURCE_WALL_MS, encode, payload
from openpilot.sunnypilot.navassist.tests.test_udp_receiver import send, stop_server
from openpilot.sunnypilot.navassist.udp_receiver import NavAssistUDPServer


class RouteIngress(unittest.TestCase):
  def test_real_udp_route_lifecycle(self):
    enabled = [False]
    store = NavAssistStore(wall_clock_ms=lambda: SOURCE_WALL_MS)
    server = NavAssistUDPServer(('127.0.0.1', 0), store, trial_enabled=lambda: enabled[0])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
      port = server.server_address[1]
      snapshot = payload(valid_for_ms=1500)
      raw = json.dumps(dict(schemaVersion=1, coordinateSystem=snapshot['coordinateSystem'], pathId=1,
                            sourcePointCount=2, sourcePointIndices=[0, 1], totalDistanceMeters=100,
                            toleranceMeters=0, points=[[23, 113], [23.001, 113.001]])).encode()
      envelope = dict(messageType='route_geometry_hello', schemaVersion=1, sessionId=snapshot['sessionId'],
                      routeRevision=snapshot['routeRevision'], routeId=hashlib.sha256(raw).hexdigest())
      self.assertIsNone(send(port, json.dumps(envelope).encode()))
      enabled[0] = True
      self.assertIsNone(send(port, json.dumps(envelope).encode()))
      self.assertIsNotNone(send(port, encode(snapshot)))
      accepted = store.current()
      self.assertFalse(send(port, json.dumps(envelope).encode())['complete'])
      bad = dict(envelope, routeRevision=envelope['routeRevision'] + 1)
      self.assertIsNone(send(port, json.dumps(bad).encode()))
      chunk = dict(envelope, messageType='route_geometry_chunk', chunkIndex=0, chunkCount=1,
                   payload=base64.b64encode(raw).decode())
      bad = dict(chunk, routeId='0' * 64)
      self.assertIsNone(send(port, json.dumps(bad).encode()))
      self.assertTrue(send(port, json.dumps(chunk).encode())['accepted'])
      for _ in range(50):
        if server.route_geometry.current(store.current(), time.monotonic_ns()) is not None:
          break
        time.sleep(.002)
      self.assertIsNotNone(server.route_geometry.current(store.current(), time.monotonic_ns()))
      self.assertIs(store.current(), accepted)
      enabled[0] = False
      self.assertIsNone(send(port, json.dumps(envelope).encode()))
      self.assertIsNone(server.route_geometry.current(store.current(), time.monotonic_ns()))
    finally:
      stop_server(server, thread)


if __name__ == '__main__': unittest.main()
