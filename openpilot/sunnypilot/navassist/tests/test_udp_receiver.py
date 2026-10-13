import json
import socket
import threading

from openpilot.sunnypilot.navassist.protocol import NavAssistStore
from openpilot.sunnypilot.navassist.server import ClientRateLimiter
from openpilot.sunnypilot.navassist.tests.test_protocol import SOURCE_WALL_MS, encode, payload
from openpilot.sunnypilot.navassist.udp_receiver import MAX_UDP_SNAPSHOT_BYTES, NavAssistUDPServer, UDP_ACK_TYPE


def run_server(*, max_requests: int = 20):
  store = NavAssistStore(wall_clock_ms=lambda: SOURCE_WALL_MS)
  server = NavAssistUDPServer(
    ("127.0.0.1", 0), store,
    rate_limiter=ClientRateLimiter(max_requests=max_requests),
  )
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  return store, server, thread


def stop_server(server: NavAssistUDPServer, thread: threading.Thread) -> None:
  server.shutdown()
  thread.join(timeout=1)
  server.server_close()
  assert not thread.is_alive()


def send(port: int, body: bytes) -> dict | None:
  with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
    client.settimeout(0.25)
    client.sendto(body, ("127.0.0.1", port))
    try:
      response, _ = client.recvfrom(1024)
    except TimeoutError:
      return None
  return json.loads(response)


def test_udp_accepts_canonical_v3_snapshot_without_credentials():
  store, server, thread = run_server()
  try:
    response = send(server.server_address[1], encode(payload()))
    assert response == {
      "messageType": UDP_ACK_TYPE,
      "schemaVersion": 3,
      "sessionId": "session-a",
      "sequence": 1,
    }
    assert store.current().snapshot.session_id == "session-a"
    assert server.diagnostics()['accepted'] == 1
    assert server.diagnostics()['received'] == 1
  finally:
    stop_server(server, thread)


def test_udp_silently_drops_replay_malformed_oversize_and_rate_limited_data():
  _, server, thread = run_server(max_requests=2)
  try:
    body = encode(payload())
    assert send(server.server_address[1], body) is not None
    assert send(server.server_address[1], body) is None
    assert send(server.server_address[1], b'{"echo_cmd":"id"}') is None
    assert send(server.server_address[1], b"x" * (MAX_UDP_SNAPSHOT_BYTES + 1)) is None
    stats = server.diagnostics()
    assert stats['received'] == 4 and stats['accepted'] == 1
    assert stats['rejected']['replay'] == 1
    assert stats['rejected']['invalidLength'] == 1
    assert 'session-a' not in json.dumps(stats)
  finally:
    stop_server(server, thread)
