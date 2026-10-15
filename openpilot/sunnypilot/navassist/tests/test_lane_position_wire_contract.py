"""Pins the exact bytes of the opt-in lane position reply.

The phone's strict ACK parser is pinned against the same two literals in
``app/src/test/kotlin/com/garan/tesnav/export/LanePositionWireContractTest.kt``.
A one-sided rename, a dropped null key or a changed type therefore fails on
whichever side moved, instead of passing both suites while quietly breaking the
link.

Both replies below are produced by the real stack: ``build_position_record`` and
``lane_position_feedback`` decide the payload and ``NavAssistUDPServer`` frames
it. Only the record path is injected, because the receiver always reads the fixed
``/dev/shm`` path, which does not exist off the device.
"""
import json
import socket
import threading
import pathlib

from openpilot.sunnypilot.navassist import position_feedback, udp_receiver
from openpilot.sunnypilot.navassist.protocol import NavAssistStore
from openpilot.sunnypilot.navassist.road_lane_position import build_position_record, write_position_record
from openpilot.sunnypilot.navassist.server import ClientRateLimiter
from openpilot.sunnypilot.navassist.tests.test_protocol import SOURCE_WALL_MS, encode, payload
from openpilot.sunnypilot.navassist.udp_receiver import NavAssistUDPServer

FIXED_NOW_NS = 1_200_000_000
CAPTURE_NS = 1_000_000_000
QUERY = {"messageType": "lane_position_request", "sessionId": "session-a", "sequence": 1}

# The phone accepts these two objects only if every key below is present.
PHONE_LANE_POSITION_KEYS = frozenset((
  'version', 'valid', 'laneIndex', 'laneCount', 'numbering',
  'source', 'ageMs', 'validForMs', 'routeRevision',
))

CONFIRMED_REPLY = (
  '{"messageType":"navassist_udp_ack","schemaVersion":3,"sessionId":"session-a","sequence":1,'
  '"lanePosition":{"version":1,"valid":true,"laneIndex":2,"laneCount":4,"numbering":"leftToRight",'
  '"source":"commaCamera","ageMs":200,"validForMs":2000,"routeRevision":1}}'
)
UNKNOWN_REPLY = (
  '{"messageType":"navassist_udp_ack","schemaVersion":3,"sessionId":"session-a","sequence":1,'
  '"lanePosition":{"version":1,"valid":false,"laneIndex":null,"laneCount":null,"numbering":"leftToRight",'
  '"source":"commaCamera","ageMs":0,"validForMs":2000,"routeRevision":1}}'
)


def _raw_send(port: int, body: bytes) -> bytes | None:
  with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
    client.settimeout(0.5)
    client.sendto(body, ("127.0.0.1", port))
    try:
      response, _ = client.recvfrom(4096)
    except TimeoutError:
      return None
  return response


def _reply_with(monkeypatch, path: pathlib.Path) -> bytes:
  """One accepted snapshot, then one lane position query, as the phone does it."""
  real = position_feedback.lane_position_feedback
  monkeypatch.setattr(udp_receiver, 'lane_position_feedback',
                      lambda snapshot: real(snapshot, path=path, now_ns=FIXED_NOW_NS))
  store = NavAssistStore(wall_clock_ms=lambda: SOURCE_WALL_MS)
  server = NavAssistUDPServer(("127.0.0.1", 0), store, rate_limiter=ClientRateLimiter(max_requests=20))
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  try:
    port = server.server_address[1]
    assert _raw_send(port, encode(payload())) is not None
    reply = _raw_send(port, json.dumps(QUERY).encode())
  finally:
    server.shutdown()
    thread.join(timeout=1)
    server.server_close()
  assert reply is not None, 'the opt-in query must be answered for an accepted session'
  return reply


def test_a_confirmed_2_of_4_reply_is_byte_exact(tmp_path, monkeypatch):
  path = tmp_path / 'road_lane_position.json'
  write_position_record(
    build_position_record(lane_index=2, lane_count=4, absolute_confirmed=True,
                          nav_session_id='session-a', route_revision=1, stable_samples=3,
                          capture_mono_ns=CAPTURE_NS),
    path=path, now_ns=FIXED_NOW_NS,
  )

  reply = _reply_with(monkeypatch, path)

  assert reply.decode() == CONFIRMED_REPLY
  lane_position = json.loads(reply)['lanePosition']
  assert set(lane_position) == PHONE_LANE_POSITION_KEYS
  assert lane_position['valid'] is True and lane_position['laneIndex'] == 2
  assert lane_position['laneCount'] == 4 and lane_position['ageMs'] == 200


def test_a_no_evidence_reply_is_byte_exact_and_keeps_every_null_key(tmp_path, monkeypatch):
  # The reader never sees a record, so it must answer "unknown", not stay silent.
  path = tmp_path / 'never-written.json'

  reply = _reply_with(monkeypatch, path)

  assert reply.decode() == UNKNOWN_REPLY
  lane_position = json.loads(reply)['lanePosition']
  assert set(lane_position) == PHONE_LANE_POSITION_KEYS
  assert lane_position['valid'] is False
  assert lane_position['laneIndex'] is None and lane_position['laneCount'] is None
  # The phone's strict parser requires the keys to exist, so null must be sent.
  assert '"laneIndex":null' in UNKNOWN_REPLY and '"laneCount":null' in UNKNOWN_REPLY


def test_the_phone_visible_key_set_matches_the_reader(tmp_path, monkeypatch):
  """The reader's own key set is what the phone whitelists, not a copy."""
  path = tmp_path / 'road_lane_position.json'
  path.write_text(json.dumps(build_position_record(
    absolute_confirmed=False, nav_session_id='session-a', route_revision=1,
    stable_samples=0, capture_mono_ns=CAPTURE_NS,
  )))

  reply = _reply_with(monkeypatch, path)

  assert set(json.loads(reply)['lanePosition']) == PHONE_LANE_POSITION_KEYS
