from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
import ipaddress
import json
import re
import socket
import threading
import time
from typing import Any

from openpilot.sunnypilot.navassist.identity import (
  KEY_ID_PATTERN,
  NavAssistDeviceIdentity,
  NavAssistPairingStore,
  public_key_id,
  verify_signature,
)


DISCOVERY_HOST = "0.0.0.0"
DISCOVERY_PORT = 7765
DISCOVERY_MAX_DATAGRAM_BYTES = 512
DISCOVERY_SCHEMA_VERSION = 3
DISCOVERY_HTTP_PORT = 7766
DISCOVERY_SNAPSHOT_PATH = "/v3/snapshot"
DISCOVERY_REQUEST_TYPE = "navassist_discovery_request"
DISCOVERY_OFFER_TYPE = "navassist_discovery_offer"
DISCOVERY_NONCE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DISCOVERY_REQUEST_KEYS = frozenset((
  "messageType", "schemaVersion", "nonce", "appKeyId", "appPublicKey", "signature",
))
DISCOVERY_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
  "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


class DiscoveryProtocolError(ValueError):
  pass


@dataclass(frozen=True)
class DiscoveryRequest:
  nonce: str
  key_id: str
  public_key: str


def request_signature_material(nonce: str, key_id: str, public_key: str) -> bytes:
  return f"{DISCOVERY_REQUEST_TYPE}\n{DISCOVERY_SCHEMA_VERSION}\n{nonce}\n{key_id}\n{public_key}".encode()


def offer_signature_material(offer: dict[str, Any]) -> bytes:
  material = f"{DISCOVERY_OFFER_TYPE}\n{DISCOVERY_SCHEMA_VERSION}\n{offer['nonce']}\n{offer['appKeyId']}\n"
  material += f"{offer['deviceId']}\n{offer['devicePublicKey']}\n{DISCOVERY_HTTP_PORT}\n{DISCOVERY_SNAPSHOT_PATH}"
  return material.encode()


def build_discovery_request(nonce: str, identity: NavAssistDeviceIdentity) -> bytes:
  if DISCOVERY_NONCE_PATTERN.fullmatch(nonce) is None:
    raise ValueError("nonce must be 32 lower-case hexadecimal characters")
  request = {
    "messageType": DISCOVERY_REQUEST_TYPE,
    "schemaVersion": DISCOVERY_SCHEMA_VERSION,
    "nonce": nonce,
    "appKeyId": identity.device_id,
    "appPublicKey": identity.public_key,
  }
  request["signature"] = identity.sign(request_signature_material(nonce, identity.device_id, identity.public_key))
  encoded = json.dumps(request, separators=(",", ":")).encode()
  if len(encoded) > DISCOVERY_MAX_DATAGRAM_BYTES:
    raise AssertionError("discovery request exceeds datagram limit")
  return encoded


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
  result: dict[str, Any] = {}
  for key, value in pairs:
    if key in result:
      raise DiscoveryProtocolError("duplicate field")
    result[key] = value
  return result


def parse_discovery_request(datagram: bytes) -> DiscoveryRequest:
  if not 0 < len(datagram) <= DISCOVERY_MAX_DATAGRAM_BYTES:
    raise DiscoveryProtocolError("invalid datagram size")
  try:
    request = json.loads(datagram.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
  except (UnicodeDecodeError, json.JSONDecodeError) as error:
    raise DiscoveryProtocolError("malformed JSON") from error
  if not isinstance(request, dict) or frozenset(request) != DISCOVERY_REQUEST_KEYS:
    raise DiscoveryProtocolError("unexpected fields")
  if request["messageType"] != DISCOVERY_REQUEST_TYPE:
    raise DiscoveryProtocolError("unexpected message type")
  if type(request["schemaVersion"]) is not int or request["schemaVersion"] != DISCOVERY_SCHEMA_VERSION:
    raise DiscoveryProtocolError("unexpected schema version")
  nonce = request["nonce"]
  key_id = request["appKeyId"]
  public_key = request["appPublicKey"]
  signature = request["signature"]
  if not isinstance(nonce, str) or DISCOVERY_NONCE_PATTERN.fullmatch(nonce) is None:
    raise DiscoveryProtocolError("invalid nonce")
  if not isinstance(key_id, str) or KEY_ID_PATTERN.fullmatch(key_id) is None:
    raise DiscoveryProtocolError("invalid app key id")
  if not isinstance(public_key, str) or not isinstance(signature, str):
    raise DiscoveryProtocolError("invalid app identity")
  try:
    if public_key_id(public_key) != key_id:
      raise DiscoveryProtocolError("app key id mismatch")
  except ValueError as error:
    raise DiscoveryProtocolError("invalid app public key") from error
  if not verify_signature(public_key, request_signature_material(nonce, key_id, public_key), signature):
    raise DiscoveryProtocolError("authentication failed")
  return DiscoveryRequest(nonce, key_id, public_key)


def build_discovery_offer(request: DiscoveryRequest, identity: NavAssistDeviceIdentity) -> bytes:
  offer = {
    "messageType": DISCOVERY_OFFER_TYPE,
    "schemaVersion": DISCOVERY_SCHEMA_VERSION,
    "nonce": request.nonce,
    "appKeyId": request.key_id,
    "deviceId": identity.device_id,
    "devicePublicKey": identity.public_key,
    "port": DISCOVERY_HTTP_PORT,
    "path": DISCOVERY_SNAPSHOT_PATH,
  }
  offer["signature"] = identity.sign(offer_signature_material(offer))
  encoded = json.dumps(offer, separators=(",", ":")).encode()
  if len(encoded) > DISCOVERY_MAX_DATAGRAM_BYTES:
    raise AssertionError("discovery offer exceeds datagram limit")
  return encoded


class DiscoveryRateLimiter:
  def __init__(self, *, max_requests_per_client: int = 5, max_requests_global: int = 20,
               window_s: float = 1.0, max_clients: int = 256,
               clock: Callable[[], float] = time.monotonic):
    if not 1 <= max_requests_per_client <= max_requests_global:
      raise ValueError("per-client limit must be positive and no greater than global limit")
    if window_s <= 0.0 or max_clients < 1:
      raise ValueError("window and client capacity must be positive")
    self._max_requests_per_client = max_requests_per_client
    self._max_requests_global = max_requests_global
    self._window_s = window_s
    self._max_clients = max_clients
    self._clock = clock
    self._global_events: deque[float] = deque()
    self._client_events: OrderedDict[str, deque[float]] = OrderedDict()
    self._lock = threading.Lock()

  def _prune(self, events: deque[float], now: float) -> None:
    while events and now - events[0] >= self._window_s:
      events.popleft()

  def allow(self, client: str) -> bool:
    now = self._clock()
    with self._lock:
      self._prune(self._global_events, now)
      if len(self._global_events) >= self._max_requests_global:
        return False

      events = self._client_events.pop(client, None)
      if events is None:
        if len(self._client_events) >= self._max_clients:
          self._client_events.popitem(last=False)
        events = deque()
      self._prune(events, now)
      self._client_events[client] = events
      if len(events) >= self._max_requests_per_client:
        return False

      events.append(now)
      self._global_events.append(now)
      return True


class DiscoveryNonceCache:
  def __init__(self, *, ttl_s: float = 2.0, max_entries: int = 512,
               clock: Callable[[], float] = time.monotonic):
    if ttl_s <= 0.0 or max_entries < 1:
      raise ValueError("nonce cache TTL and capacity must be positive")
    self._ttl_s = ttl_s
    self._max_entries = max_entries
    self._clock = clock
    self._entries: OrderedDict[tuple[str, str], float] = OrderedDict()
    self._lock = threading.Lock()

  def accept_once(self, client: str, nonce: str) -> bool:
    now = self._clock()
    key = (client, nonce)
    with self._lock:
      while self._entries:
        oldest_key, expires_at = next(iter(self._entries.items()))
        if expires_at > now:
          break
        self._entries.pop(oldest_key)
      if key in self._entries:
        return False
      if len(self._entries) >= self._max_entries:
        self._entries.popitem(last=False)
      self._entries[key] = now + self._ttl_s
      return True


def is_private_discovery_client(client: str) -> bool:
  try:
    address = ipaddress.ip_address(client)
  except ValueError:
    return False
  return isinstance(address, ipaddress.IPv4Address) and any(address in network for network in DISCOVERY_PRIVATE_NETWORKS)


class NavAssistDiscoveryServer:
  def __init__(self, address: tuple[str, int], identity: NavAssistDeviceIdentity, pairing: NavAssistPairingStore, *,
               is_offroad: Callable[[], bool],
               rate_limiter: DiscoveryRateLimiter | None = None, nonce_cache: DiscoveryNonceCache | None = None,
               client_allowed: Callable[[str], bool] = is_private_discovery_client, socket_timeout_s: float = 0.2):
    self._identity = identity
    self._pairing = pairing
    self._is_offroad = is_offroad
    self._rate_limiter = rate_limiter or DiscoveryRateLimiter()
    self._nonce_cache = nonce_cache or DiscoveryNonceCache()
    self._client_allowed = client_allowed
    self._stop_event = threading.Event()
    self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
      self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
      self._socket.settimeout(socket_timeout_s)
      self._socket.bind(address)
    except BaseException:
      self._socket.close()
      raise

  @property
  def server_address(self) -> tuple[str, int]:
    address = self._socket.getsockname()
    return address[0], address[1]

  @property
  def server_port(self) -> int:
    return self.server_address[1]

  def serve_forever(self) -> None:
    while not self._stop_event.is_set():
      try:
        datagram, client_address = self._socket.recvfrom(DISCOVERY_MAX_DATAGRAM_BYTES + 1)
      except TimeoutError:
        continue
      except OSError:
        if self._stop_event.is_set():
          break
        raise

      client_ip = client_address[0]
      if not self._client_allowed(client_ip) or not self._rate_limiter.allow(client_ip):
        continue
      try:
        request = parse_discovery_request(datagram)
        if not self._pairing.authorize_or_pair(
          request.key_id, request.public_key, is_offroad=self._is_offroad(),
        ):
          continue
        if not self._nonce_cache.accept_once(f"{client_ip}:{request.key_id}", request.nonce):
          continue
        offer = build_discovery_offer(request, self._identity)
        self._socket.sendto(offer, client_address)
      except (DiscoveryProtocolError, OSError, RuntimeError):
        # UDP discovery is intentionally silent for malformed, unauthenticated,
        # rate-limited, or unreachable requests. Never log request material.
        continue

  def shutdown(self) -> None:
    self._stop_event.set()

  def server_close(self) -> None:
    self._socket.close()
