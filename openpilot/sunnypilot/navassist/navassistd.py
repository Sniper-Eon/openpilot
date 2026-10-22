#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path
import threading
import time

from openpilot.cereal import log, messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.navassist.discovery import DISCOVERY_HOST, DISCOVERY_PORT, NavAssistDiscoveryServer
from openpilot.sunnypilot.navassist.identity import NavAssistDeviceIdentity, NavAssistPairingStore
from openpilot.sunnypilot.navassist.protocol import NavAssistStore
from openpilot.sunnypilot.navassist.publisher import build_nav_assist_message
from openpilot.sunnypilot.navassist.server import NavAssistHTTPServer
from openpilot.sunnypilot.navassist.udp_receiver import NavAssistUDPServer, UDP_SNAPSHOT_PORT
from openpilot.sunnypilot.navassist.diagnostics import ingress_status_path
from openpilot.sunnypilot.navassist.lane_position import estimate_ego_lane
from openpilot.sunnypilot.navassist.settings import atomic_json


LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 7766
PUBLISH_HZ = 20
LOCALIZATION_MAX_AGE_NS = 500_000_000
LOCAL_POSITION_MAX_STD_M = 10.0
REPLAY_CHECKPOINT_PATH = "/dev/shm/navassist_replay_state.json"
MAINTENANCE_REFRESH_NS = 1_000_000_000
LANE_TOPOLOGY_MAX_AGE_NS = 150_000_000
LANE_ANCHOR_PATH = Path("/dev/shm/lane_anchor_state.json")
LANE_POSITION_PATH = Path("/dev/shm/road_lane_position.json")
LANE_POSITION_HOLD_NS = 1_000_000_000
LANE_POSITION_WRITE_NS = 100_000_000
LANE_POSITION_MIN_SPEED_MPS = 1.0
LANE_POSITION_STABLE_FRAMES = 3
HOLDABLE_REASONS = frozenset(("noSameDirectionAnchor", "amapLaneCountUnknown", "topologyUnavailable", "visibleGeometryInvalid"))


LANE_COUNT_CACHE_MAX_NS = 60_000_000_000
_lane_count_cache = {"indices": (), "total": None, "session": None, "route": None, "ns": 0}


def cached_amap_lanes(snapshot, now_ns: int, *, update: bool = True):
  """Reuse the last AMap lane set for 5s; route/session changes clear it."""
  try:
    lanes = tuple(int(lane.index) for lane in snapshot.lanes)
    total = int(snapshot.lane_total_count)
    session = str(snapshot.session_id)
    route = int(snapshot.route_revision)
  except (AttributeError, TypeError, ValueError):
    return (), -1
  if lanes and update:
    _lane_count_cache.update(indices=lanes, total=total, session=session, route=route, ns=now_ns)
    return lanes, total
  if (_lane_count_cache["session"] == session and _lane_count_cache["route"] == route and
      0 <= now_ns - int(_lane_count_cache["ns"]) <= LANE_COUNT_CACHE_MAX_NS):
    return tuple(_lane_count_cache["indices"]), _lane_count_cache["total"]
  return (), -1


def read_lane_anchors(now_ns: int) -> dict:
  try:
    data = json.loads(LANE_ANCHOR_PATH.read_text())
    if 0 <= now_ns - int(data.get("publish_mono_ns", 0)) <= LANE_TOPOLOGY_MAX_AGE_NS:
      return data
  except (OSError, ValueError, TypeError):
    pass
  return {}


def lane_position_estimate(sm, current, now_ns: int) -> dict:
  topology = sm["laneTopologyStateSP"]
  anchors = read_lane_anchors(now_ns)
  seen = bool(sm.seen["laneTopologyStateSP"] and sm.alive["laneTopologyStateSP"]
              and sm.valid["laneTopologyStateSP"])
  age_ns = now_ns - int(sm.logMonoTime["laneTopologyStateSP"])
  fresh = bool(seen and 0 <= age_ns <= LANE_TOPOLOGY_MAX_AGE_NS)
  valid = bool(fresh and topology.valid and not topology.stale and not topology.ambiguous)
  nav_fresh = bool(current is not None and not current.is_stale(now_ns))
  lanes, total = cached_amap_lanes(current.snapshot, now_ns, update=nav_fresh) if current is not None else ((), -1)
  return estimate_ego_lane(
    amap_lane_indices=lanes,
    amap_total_count=total if 1 <= total <= 16 else None,
    visible_lane_count=int(topology.visibleLaneCount) if seen else 0,
    ego_visible_index=int(topology.egoLaneIndexFromLeft) if seen else -1,
    lanes_left_same_direction=int(anchors.get("lanes_left_same_direction", -1)) if seen else -1,
    lanes_right_same_direction=int(anchors.get("lanes_right_same_direction", -1)) if seen else -1,
    left_anchor=str(anchors.get("left_anchor_source", "unknown")) if seen else "unknown",
    right_anchor=str(anchors.get("right_anchor_source", "unknown")) if seen else "unknown",
    topology_fresh=fresh,
    topology_valid=valid,
  ).to_dict()


def write_lane_position(*, valid: bool, position: dict, current, now_ns: int, stable_samples: int) -> None:
  index = position.get("lane_index_from_left")
  count = position.get("lane_count")
  payload = {
    "version": 1,
    "valid": bool(valid),
    "lane_index": int(index) + 1 if valid and type(index) is int else 0,
    "lane_count": int(count) if valid and type(count) is int else None,
    "numbering": "leftToRight",
    "source": "commaCamera",
    "absolute_confirmed": bool(valid),
    "stable_samples": int(stable_samples),
    # Diagnostic evidence only. Existing readers still require valid=true,
    # absolute_confirmed=true and a fresh confirmed index for control.
    "estimate": dict(position),
    "nav_session_id": str(current.snapshot.session_id) if current is not None else "",
    "route_revision": int(current.snapshot.route_revision) if current is not None else 0,
    "capture_mono_ns": int(now_ns),
  }
  try:
    atomic_json(LANE_POSITION_PATH, payload)
  except OSError:
    pass


def update_lane_position(sm, current, now_ns: int, state: dict) -> None:
  car_ok = bool(sm.seen["carState"] and sm.alive["carState"] and sm.valid["carState"])
  speed = float(sm["carState"].vEgo) if car_ok else 0.0
  position = lane_position_estimate(sm, current, now_ns)
  candidate = position.get("lane_index_from_left")
  estimate_valid = bool(position.get("valid") is True and speed >= LANE_POSITION_MIN_SPEED_MPS)
  if estimate_valid and type(candidate) is int:
    # A different candidate lane number restarts the confirmation count.
    if state.get("candidate_index") != candidate:
      state["candidate_index"] = candidate
      state["stable"] = 0
    state["stable"] = min(int(state["stable"]) + 1, 99)
    state["last_valid_ns"] = now_ns
  else:
    state["stable"] = 0
    state["candidate_index"] = None
  valid = bool(estimate_valid and int(state["stable"]) >= LANE_POSITION_STABLE_FRAMES)
  holdable = position.get("reason") in HOLDABLE_REASONS
  if not valid and holdable and state["last_valid_ns"] and \
      now_ns - int(state["last_valid_ns"]) <= LANE_POSITION_HOLD_NS:
    # Leave the last valid file in place; position_feedback ages it out.
    return
  if now_ns - int(state["last_write_ns"]) < LANE_POSITION_WRITE_NS:
    return
  write_lane_position(valid=valid, position=position, current=current,
                      now_ns=now_ns, stable_samples=int(state["stable"]))
  state["last_write_ns"] = now_ns
  if not valid:
    state["last_valid_ns"] = 0


def local_position_std_m(location) -> float:
  position_ecef = location.positionECEF
  if not position_ecef.valid or len(position_ecef.std) < 3:
    return math.inf
  values = tuple(float(position_ecef.std[i]) for i in range(3))
  if not all(math.isfinite(value) and value >= 0.0 for value in values):
    return math.inf
  return math.sqrt(sum(value * value for value in values))


def local_localization_valid(sm, now_ns: int) -> bool:
  service = "liveLocationKalman"
  location = sm[service]
  age_ns = now_ns - sm.logMonoTime[service]
  return bool(
    sm.seen[service] and sm.alive[service] and sm.valid[service]
    and 0 <= age_ns <= LOCALIZATION_MAX_AGE_NS
    and location.status == log.LiveLocationKalman.Status.valid and location.positionGeodetic.valid
    and len(location.positionGeodetic.value) >= 2
    and location.gpsOK and location.inputsOK and location.sensorsOK and location.deviceStable
    and not location.excessiveResets and local_position_std_m(location) <= LOCAL_POSITION_MAX_STD_M
  )


def main() -> None:
  params = Params()
  identity = NavAssistDeviceIdentity.load_or_create(params=params)
  pairing = NavAssistPairingStore(params)

  store = NavAssistStore(checkpoint_path=REPLAY_CHECKPOINT_PATH)
  server = NavAssistHTTPServer((LISTEN_HOST, LISTEN_PORT), store, identity, pairing)
  udp_server = NavAssistUDPServer((LISTEN_HOST, UDP_SNAPSHOT_PORT), store)
  try:
    discovery_server = NavAssistDiscoveryServer(
      (DISCOVERY_HOST, DISCOVERY_PORT), identity, pairing, is_offroad=lambda: params.get_bool("IsOffroad"),
    )
  except BaseException:
    udp_server.server_close()
    server.server_close()
    raise
  server_thread = threading.Thread(target=server.serve_forever, name="navassist-http", daemon=True)
  discovery_thread = threading.Thread(
    target=discovery_server.serve_forever, name="navassist-discovery", daemon=True,
  )
  udp_thread = threading.Thread(target=udp_server.serve_forever, name="navassist-udp", daemon=True)
  server_started = False
  discovery_started = False
  udp_started = False
  try:
    server_thread.start()
    server_started = True
    discovery_thread.start()
    discovery_started = True
    udp_thread.start()
    udp_started = True
    cloudlog.warning(
      "navassistd receiver online on HTTP port %d, discovery port %d and data-only UDP port %d",
      LISTEN_PORT, DISCOVERY_PORT, UDP_SNAPSHOT_PORT,
    )

    pm = messaging.PubMaster(["navAssistStateSP"])
    sm = messaging.SubMaster(["liveLocationKalman", "laneTopologyStateSP", "carState"])
    ratekeeper = Ratekeeper(PUBLISH_HZ)
    next_maintenance_ns = 0
    lane_position_state = {"stable": 0, "last_valid_ns": 0, "last_write_ns": 0, "candidate_index": None}
    while True:
      sm.update(0)
      now_ns = time.monotonic_ns()
      if now_ns >= next_maintenance_ns:
        if params.get_bool("NavAssistPairingReset"):
          pairing.reset()
          store.reset()
          params.put_bool("NavAssistPairingReset", False, block=True)
        next_maintenance_ns = now_ns + MAINTENANCE_REFRESH_NS
        try:
          atomic_json(ingress_status_path(), {'updated_mono_ns': now_ns, **udp_server.diagnostics()})
        except OSError:
          pass
      update_lane_position(sm, store.current(), now_ns, lane_position_state)
      localization_valid = local_localization_valid(sm, now_ns)
      message = build_nav_assist_message(
        store.current(), now_ns, local_localization_valid=localization_valid,
      )
      pm.send("navAssistStateSP", message)
      ratekeeper.keep_time()
  finally:
    if udp_started:
      udp_server.shutdown()
    if discovery_started:
      discovery_server.shutdown()
    if server_started:
      server.shutdown()
    if discovery_started:
      discovery_thread.join(timeout=2)
    if server_started:
      server_thread.join(timeout=2)
    if udp_started:
      udp_thread.join(timeout=2)
    discovery_server.server_close()
    udp_server.server_close()
    server.server_close()


if __name__ == "__main__":
  main()
