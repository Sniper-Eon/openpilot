import http.client
import json
import threading

from openpilot.sunnypilot.navassist.identity import NavAssistDeviceIdentity, NavAssistPairingStore
from openpilot.sunnypilot.navassist.protocol import NavAssistStore
from openpilot.sunnypilot.navassist.server import (
  KEY_ID_HEADER,
  SIGNATURE_HEADER,
  SNAPSHOT_PATH,
  ClientRateLimiter,
  NavAssistHTTPServer,
  snapshot_signature_material,
)
from openpilot.sunnypilot.navassist.tests.test_protocol import SOURCE_WALL_MS, encode, payload


class FakeParams:
  def __init__(self):
    self.values = {}

  def get(self, key):
    return self.values.get(key)

  def put(self, key, value, block=False):
    assert block
    self.values[key] = value


def store():
  return NavAssistStore(wall_clock_ms=lambda: SOURCE_WALL_MS)


def identities(tmp_path):
  device = NavAssistDeviceIdentity.load_or_create(tmp_path / "device.pem")
  app = NavAssistDeviceIdentity.load_or_create(tmp_path / "app.pem")
  pairing = NavAssistPairingStore(FakeParams())
  assert pairing.authorize_or_pair(app.device_id, app.public_key, is_offroad=True)
  return device, app, pairing


def post(port: int, body: bytes, key_id: str | None, signature: str | None):
  connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
  headers = {"Content-Type": "application/json"}
  if key_id is not None:
    headers[KEY_ID_HEADER] = key_id
  if signature is not None:
    headers[SIGNATURE_HEADER] = signature
  connection.request("POST", SNAPSHOT_PATH, body=body, headers=headers)
  response = connection.getresponse()
  result = response.status, json.loads(response.read())
  connection.close()
  return result


def run_server(store: NavAssistStore, identity: NavAssistDeviceIdentity, pairing: NavAssistPairingStore, *,
               rate_limiter=None):
  server = NavAssistHTTPServer(("127.0.0.1", 0), store, identity, pairing, rate_limiter=rate_limiter)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  return server, thread


def stop_server(server: NavAssistHTTPServer, thread: threading.Thread) -> None:
  server.shutdown()
  server.server_close()
  thread.join(timeout=2)
  assert not thread.is_alive()


def test_http_accepts_authenticated_snapshot_and_rejects_replay(tmp_path):
  device, app, pairing = identities(tmp_path)
  server, thread = run_server(store(), device, pairing)
  try:
    body = encode(payload())
    signature = app.sign(snapshot_signature_material(device.device_id, app.device_id, SNAPSHOT_PATH, body))
    status, result = post(server.server_port, body, app.device_id, signature)
    assert status == 202
    assert result == {"accepted": True, "sessionId": "session-a", "sequence": 1, "routeRevision": 1}

    status, result = post(server.server_port, body, app.device_id, signature)
    assert status == 409
    assert result == {"accepted": False, "reason": "replay"}
  finally:
    stop_server(server, thread)


def test_http_rejects_missing_signature_and_rate_limits_before_parsing(tmp_path):
  device, app, pairing = identities(tmp_path)
  server, thread = run_server(store(), device, pairing, rate_limiter=ClientRateLimiter(max_requests=1))
  try:
    body = encode(payload())
    assert post(server.server_port, body, app.device_id, None) == \
      (401, {"accepted": False, "reason": "authentication"})
    assert post(server.server_port, body, app.device_id, None) == \
      (429, {"accepted": False, "reason": "rate_limited"})
  finally:
    stop_server(server, thread)


def test_http_signature_is_bound_to_device_app_path_and_body(tmp_path):
  device, app, pairing = identities(tmp_path)
  other_device = NavAssistDeviceIdentity.load_or_create(tmp_path / "other-device.pem")
  server, thread = run_server(store(), device, pairing)
  try:
    body = encode(payload())
    wrong_device_signature = app.sign(
      snapshot_signature_material(other_device.device_id, app.device_id, SNAPSHOT_PATH, body),
    )
    assert post(server.server_port, body, app.device_id, wrong_device_signature) == \
      (401, {"accepted": False, "reason": "authentication"})

    valid_signature = app.sign(snapshot_signature_material(device.device_id, app.device_id, SNAPSHOT_PATH, body))
    assert post(server.server_port, body + b" ", app.device_id, valid_signature) == \
      (401, {"accepted": False, "reason": "authentication"})
  finally:
    stop_server(server, thread)


def test_http_server_has_a_hard_concurrency_cap(tmp_path):
  device, _, pairing = identities(tmp_path)
  server = NavAssistHTTPServer(("127.0.0.1", 0), store(), device, pairing, max_concurrent_requests=2)
  try:
    assert server._request_slots.acquire(blocking=False)
    assert server._request_slots.acquire(blocking=False)
    assert not server._request_slots.acquire(blocking=False)
    server._request_slots.release()
    server._request_slots.release()
  finally:
    server.server_close()
