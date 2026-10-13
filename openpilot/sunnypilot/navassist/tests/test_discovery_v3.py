import json
import socket
import threading

import pytest

from openpilot.sunnypilot.navassist.discovery import (
  DISCOVERY_MAX_DATAGRAM_BYTES,
  NavAssistDiscoveryServer,
  build_discovery_offer,
  build_discovery_request,
  offer_signature_material,
  parse_discovery_request,
)
from openpilot.sunnypilot.navassist.identity import NavAssistDeviceIdentity, NavAssistPairingStore, verify_signature


NONCE = "00112233445566778899aabbccddeeff"


def test_signed_discovery_request_and_offer_fit_the_512_byte_wire_limit(tmp_path):
  app = NavAssistDeviceIdentity.load_or_create(tmp_path / "app.pem")
  device = NavAssistDeviceIdentity.load_or_create(tmp_path / "device.pem")

  request_bytes = build_discovery_request(NONCE, app)
  request = parse_discovery_request(request_bytes)
  assert request.key_id == app.device_id
  assert request.public_key == app.public_key
  assert len(request_bytes) <= 403 < DISCOVERY_MAX_DATAGRAM_BYTES

  offer_bytes = build_discovery_offer(request, device)
  offer = json.loads(offer_bytes)
  assert offer == {
    "messageType": "navassist_discovery_offer",
    "schemaVersion": 3,
    "nonce": NONCE,
    "appKeyId": app.device_id,
    "deviceId": device.device_id,
    "devicePublicKey": device.public_key,
    "port": 7766,
    "path": "/v3/snapshot",
    "signature": offer["signature"],
  }
  assert verify_signature(device.public_key, offer_signature_material(offer), offer["signature"])
  assert len(offer_bytes) <= 484 < DISCOVERY_MAX_DATAGRAM_BYTES


class FakeParams:
  def __init__(self):
    self.values = {}

  def get(self, key):
    return self.values.get(key)

  def put(self, key, value, block=False):
    assert block
    self.values[key] = value


def test_server_pairs_each_new_app_only_offroad_then_recognizes_both_onroad(tmp_path):
  device = NavAssistDeviceIdentity.load_or_create(tmp_path / "device.pem")
  first = NavAssistDeviceIdentity.load_or_create(tmp_path / "first.pem")
  second = NavAssistDeviceIdentity.load_or_create(tmp_path / "second.pem")
  pairing = NavAssistPairingStore(FakeParams())
  offroad = [False]
  server = NavAssistDiscoveryServer(
    ("127.0.0.1", 0), device, pairing, is_offroad=lambda: offroad[0],
    client_allowed=lambda client: client == "127.0.0.1", socket_timeout_s=0.02,
  )
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  client.settimeout(0.1)
  try:
    client.sendto(build_discovery_request("0" * 32, first), server.server_address)
    with pytest.raises(TimeoutError):
      client.recvfrom(DISCOVERY_MAX_DATAGRAM_BYTES + 1)

    offroad[0] = True
    client.sendto(build_discovery_request("1" * 32, first), server.server_address)
    assert json.loads(client.recvfrom(DISCOVERY_MAX_DATAGRAM_BYTES + 1)[0])["deviceId"] == device.device_id

    offroad[0] = False
    client.sendto(build_discovery_request("2" * 32, first), server.server_address)
    assert json.loads(client.recvfrom(DISCOVERY_MAX_DATAGRAM_BYTES + 1)[0])["appKeyId"] == first.device_id

    offroad[0] = True
    client.sendto(build_discovery_request("3" * 32, second), server.server_address)
    assert json.loads(client.recvfrom(DISCOVERY_MAX_DATAGRAM_BYTES + 1)[0])["appKeyId"] == second.device_id

    offroad[0] = False
    client.sendto(build_discovery_request("4" * 32, second), server.server_address)
    assert json.loads(client.recvfrom(DISCOVERY_MAX_DATAGRAM_BYTES + 1)[0])["appKeyId"] == second.device_id
  finally:
    client.close()
    server.shutdown()
    thread.join(timeout=1)
    server.server_close()
