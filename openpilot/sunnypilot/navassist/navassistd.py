#!/usr/bin/env python3
from __future__ import annotations

import math
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
from openpilot.sunnypilot.navassist.settings import atomic_json


LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 7766
PUBLISH_HZ = 20
LOCALIZATION_MAX_AGE_NS = 500_000_000
LOCAL_POSITION_MAX_STD_M = 10.0
REPLAY_CHECKPOINT_PATH = "/dev/shm/navassist_replay_state.json"
MAINTENANCE_REFRESH_NS = 1_000_000_000


def local_position_std_m(location) -> float:
  position_ecef = location.positionECEF
  if not position_ecef.valid or len(position_ecef.std) < 3:
    return math.inf
  values = tuple(float(value) for value in position_ecef.std[:3])
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
    sm = messaging.SubMaster(["liveLocationKalman"])
    ratekeeper = Ratekeeper(PUBLISH_HZ)
    next_maintenance_ns = 0
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
