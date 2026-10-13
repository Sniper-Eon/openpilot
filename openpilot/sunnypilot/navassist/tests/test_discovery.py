import json

import pytest

from openpilot.sunnypilot.navassist.discovery import (
  DISCOVERY_HTTP_PORT,
  DISCOVERY_MAX_DATAGRAM_BYTES,
  DISCOVERY_OFFER_TYPE,
  DISCOVERY_REQUEST_TYPE,
  DISCOVERY_SCHEMA_VERSION,
  DISCOVERY_SNAPSHOT_PATH,
  DiscoveryNonceCache,
  DiscoveryProtocolError,
  DiscoveryRateLimiter,
  build_discovery_offer,
  build_discovery_request,
  is_private_discovery_client,
  offer_signature_material,
  parse_discovery_request,
  request_signature_material,
)
from openpilot.sunnypilot.navassist.identity import NavAssistDeviceIdentity, verify_signature
from openpilot.sunnypilot.navassist.navassistd import LISTEN_PORT
from openpilot.sunnypilot.navassist.server import SNAPSHOT_PATH


NONCE = "00112233445566778899aabbccddeeff"


def test_discovery_signature_material_is_language_independent():
  assert request_signature_material(NONCE, "a" * 32, "B" * 122) == (
    "navassist_discovery_request\n3\n00112233445566778899aabbccddeeff\n"
    + "a" * 32 + "\n" + "B" * 122
  ).encode()
  offer = {
    "nonce": NONCE,
    "appKeyId": "a" * 32,
    "deviceId": "b" * 32,
    "devicePublicKey": "C" * 122,
  }
  assert offer_signature_material(offer) == (
    "navassist_discovery_offer\n3\n00112233445566778899aabbccddeeff\n"
    + "a" * 32 + "\n" + "b" * 32 + "\n" + "C" * 122 + "\n7766\n/v3/snapshot"
  ).encode()


def test_offer_endpoint_matches_the_http_receiver():
  assert DISCOVERY_HTTP_PORT == LISTEN_PORT
  assert DISCOVERY_SNAPSHOT_PATH == SNAPSHOT_PATH


def test_strict_request_parser_and_offer_contract(tmp_path):
  app = NavAssistDeviceIdentity.load_or_create(tmp_path / "app.pem")
  device = NavAssistDeviceIdentity.load_or_create(tmp_path / "device.pem")
  request_bytes = build_discovery_request(NONCE, app)
  request = parse_discovery_request(request_bytes)
  assert request.nonce == NONCE
  assert request.key_id == app.device_id

  offer_bytes = build_discovery_offer(request, device)
  assert len(offer_bytes) <= DISCOVERY_MAX_DATAGRAM_BYTES
  offer = json.loads(offer_bytes)
  assert offer["messageType"] == DISCOVERY_OFFER_TYPE
  assert offer["schemaVersion"] == DISCOVERY_SCHEMA_VERSION
  assert offer["nonce"] == NONCE
  assert offer["appKeyId"] == app.device_id
  assert offer["deviceId"] == device.device_id
  assert offer["devicePublicKey"] == device.public_key
  assert offer["port"] == DISCOVERY_HTTP_PORT
  assert offer["path"] == DISCOVERY_SNAPSHOT_PATH
  assert verify_signature(device.public_key, offer_signature_material(offer), offer["signature"])


def test_request_parser_rejects_tampering_unknown_duplicate_and_oversized_fields(tmp_path):
  app = NavAssistDeviceIdentity.load_or_create(tmp_path / "app.pem")
  valid = build_discovery_request(NONCE, app)
  request = json.loads(valid)
  wrong_signature = dict(request, signature="A")
  unknown = dict(request, extra="unexpected")
  duplicate = valid.replace(b'"nonce":', b'"nonce":"' + NONCE.encode() + b'","nonce":', 1)
  malformed = [
    b"",
    b"not-json",
    b"x" * (DISCOVERY_MAX_DATAGRAM_BYTES + 1),
    json.dumps(wrong_signature, separators=(",", ":")).encode(),
    json.dumps(unknown, separators=(",", ":")).encode(),
    duplicate,
    valid.replace(b'"schemaVersion":3', b'"schemaVersion":"3"'),
    valid.replace(DISCOVERY_REQUEST_TYPE.encode(), b"wrong_message_type"),
  ]
  for datagram in malformed:
    with pytest.raises(DiscoveryProtocolError):
      parse_discovery_request(datagram)


def test_discovery_rate_limiter_bounds_per_client_global_rate_and_client_memory():
  now = [1.0]
  limiter = DiscoveryRateLimiter(
    max_requests_per_client=1, max_requests_global=2, window_s=1.0, max_clients=1, clock=lambda: now[0],
  )
  assert limiter.allow("192.168.1.1")
  assert not limiter.allow("192.168.1.1")
  assert limiter.allow("192.168.1.2")
  assert not limiter.allow("192.168.1.3")
  assert len(limiter._client_events) <= 1
  now[0] += 1.0
  assert limiter.allow("192.168.1.3")


def test_discovery_accepts_only_rfc1918_sources():
  for address in ("10.1.2.3", "172.16.0.1", "172.31.255.254", "192.168.53.232"):
    assert is_private_discovery_client(address)
  for address in ("8.8.8.8", "172.32.0.1", "169.254.1.1", "0.0.0.0", "127.0.0.1", "::1", "not-an-address"):
    assert not is_private_discovery_client(address)


def test_nonce_cache_suppresses_short_replay_and_has_bounded_memory():
  now = [1.0]
  cache = DiscoveryNonceCache(ttl_s=2.0, max_entries=2, clock=lambda: now[0])
  assert cache.accept_once("192.168.1.1:app-a", "0" * 32)
  assert not cache.accept_once("192.168.1.1:app-a", "0" * 32)
  assert cache.accept_once("192.168.1.2:app-a", "0" * 32)
  assert cache.accept_once("192.168.1.3:app-b", "1" * 32)
  assert len(cache._entries) <= 2
  now[0] += 2.0
  assert cache.accept_once("192.168.1.1:app-a", "0" * 32)
