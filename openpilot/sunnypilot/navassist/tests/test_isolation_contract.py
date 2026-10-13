from pathlib import Path
from types import SimpleNamespace

from openpilot.cereal import log
from openpilot.sunnypilot.navassist.lane_topologyd import IMAGE_CLASSIFIER_DIVISOR, services_healthy
from openpilot.sunnypilot.navassist.navassistd import LOCALIZATION_MAX_AGE_NS, local_localization_valid
from openpilot.sunnypilot.hardware.profile import HardwareProfile
from openpilot.system.manager import process_config


ROOT = Path(__file__).resolve().parents[3]
NAVASSIST = ROOT / "sunnypilot/navassist"


def test_network_ingress_never_imports_or_publishes_vehicle_control_interfaces():
  # The independent recorder reads vehicle fields but is not network ingress.
  sources = "\n".join(path.read_text() for path in NAVASSIST.glob("*.py") if path.name != 'diagnosticsd.py')
  for forbidden in ("sendcan", "carControl.actuators", "desiredCurvature", "steeringAngleDeg"):
    assert forbidden not in sources
  assert 'PubMaster(["navAssistStateSP"])' in (NAVASSIST / "navassistd.py").read_text()


def test_navigation_recorder_is_read_only():
  source = (NAVASSIST / 'diagnosticsd.py').read_text()
  assert 'messaging.SubMaster' in source
  for forbidden in ('PubMaster(', 'sendcan', 'CarController', 'Params().put'):
    assert forbidden not in source


def test_receiver_is_always_available_and_lane_observer_stays_onroad():
  process_config = (ROOT / "system/manager/process_config.py").read_text()
  assert 'PythonProcess("navassistd", "openpilot.sunnypilot.navassist.navassistd", navassist_receiver_ready)' in process_config
  assert 'PythonProcess("lane_topologyd", "openpilot.sunnypilot.navassist.lane_topologyd", navassist_lane_observer_ready)' in process_config
  assert 'PythonProcess("nav_lane_intentd", "openpilot.sunnypilot.navassist.nav_lane_intentd", navassist_lane_observer_ready)' in process_config
  receiver = process_config.split("def navassist_receiver_ready", 1)[1].split("def ", 1)[0]
  assert "HardwareProfile.C3XL" in receiver
  assert 'brand == "tesla"' not in receiver
  assert "NavAssistToken" not in receiver
  assert "NavAssistTrackMode" not in receiver
  assert "NavAssistTrackGeofence" not in receiver
  lane_observer = process_config.split("def navassist_lane_observer_ready", 1)[1].split("def ", 1)[0]
  assert "started" in lane_observer
  assert 'CP.brand == "tesla"' in lane_observer
  assert "navassist_receiver_ready" in lane_observer

  lane_daemon = (NAVASSIST / "lane_topologyd.py").read_text()
  assert "client.timestamp_eof" in lane_daemon
  assert "frame.timestamp_eof" not in lane_daemon
  assert "LaneTopologyObserver(frame_divisor=1)" in lane_daemon
  assert "bridge.last_frame_id % IMAGE_CLASSIFIER_DIVISOR" in lane_daemon
  assert IMAGE_CLASSIFIER_DIVISOR == 2

  navassist_daemon = (NAVASSIST / "navassistd.py").read_text()
  assert "NavAssistDeviceIdentity.load_or_create(params=params)" in navassist_daemon
  assert "NavAssistPairingStore(params)" in navassist_daemon
  assert "NavAssistDiscoveryServer(" in navassist_daemon
  assert "NavAssistToken" not in navassist_daemon
  assert 'params.get_bool("NavAssistTrackMode")' not in navassist_daemon
  assert "Geofence" not in navassist_daemon
  assert "discovery_server.shutdown()" in navassist_daemon
  assert "discovery_thread.join(timeout=2)" in navassist_daemon


def test_developer_settings_show_automatic_pairing_without_token_or_track_toggle():
  settings_sources = (
    ROOT / "selfdrive/ui/layouts/settings/developer.py",
    ROOT / "selfdrive/ui/mici/layouts/settings/developer.py",
  )
  for path in settings_sources:
    source = path.read_text()
    assert 'get("NavAssistPairedApp")' in source
    assert "NavAssistToken" not in source
    assert "NavAssistTrackMode" not in source
    assert "pair" in source.lower()


def test_navigation_control_has_no_geofence_configuration_or_gate():
  params_keys = (ROOT / "common/params_keys.h").read_text()
  schema = (ROOT / "cereal/custom.capnp").read_text()
  publisher = (NAVASSIST / "publisher.py").read_text()
  assert "NavAssistTrackGeofence" not in params_keys
  assert "trackGeofenceValid @" not in schema
  assert "outsideTrack @" not in schema
  assert "track_geofence" not in publisher
  assert "outsideTrack" not in publisher


def test_planner_uses_common_target_seam_and_controlsd_is_untouched():
  common_planner = (ROOT / "sunnypilot/selfdrive/controls/lib/longitudinal_planner.py").read_text()
  controlsd = (ROOT / "selfdrive/controls/controlsd.py").read_text()
  assert "LongitudinalPlanSource.navAssist" in common_planner
  assert "navAssistStateSP" not in controlsd


def test_both_model_runners_consume_typed_navigation_intent_and_lane_change_blocks():
  desire_helper = (ROOT / "selfdrive/controls/lib/desire_helper.py").read_text()
  assert "laneChangeAuthorized" not in desire_helper
  runners = (
    ROOT / "selfdrive/modeld/modeld.py",
    ROOT / "sunnypilot/modeld_v2/modeld.py",
  )
  for runner in runners:
    source = runner.read_text()
    assert '"navLaneIntentSP"' in source
    assert '"laneTopologyStateSP"' in source
    assert "nav_lane_intent=nav_lane_intent" in source
    assert "LaneChangeBoundaryBlocker" in source
    assert "LINE_BLOCKER.update(" in source
    assert "lane_topology_nav_crossing_allowed" in source
    assert "nav_lane_crossing_policy(nav_lane_intent" in source
    assert "left_crossing_allowed=" in source
    assert "right_crossing_allowed=" in source
    assert "left_line_blocked=left_line_blocked" in source
    assert "right_line_blocked=right_line_blocked" in source
    assert "navAssistStateSP" not in source


def test_local_localization_requires_alive_valid_and_bounded_age():
  now_ns = 1_000_000_000
  location = SimpleNamespace(
    status=log.LiveLocationKalman.Status.valid,
    positionGeodetic=SimpleNamespace(valid=True, value=[31.2, 121.4, 0.0]),
    positionECEF=SimpleNamespace(valid=True, std=[2.0, 2.0, 2.0]),
    gpsOK=True,
    inputsOK=True,
    sensorsOK=True,
    deviceStable=True,
    excessiveResets=False,
  )

  class FakeSM:
    seen = {"liveLocationKalman": True}
    alive = {"liveLocationKalman": True}
    valid = {"liveLocationKalman": True}
    logMonoTime = {"liveLocationKalman": now_ns - LOCALIZATION_MAX_AGE_NS}

    def __getitem__(self, _key):
      return location

  sm = FakeSM()
  assert local_localization_valid(sm, now_ns)
  sm.alive["liveLocationKalman"] = False
  assert not local_localization_valid(sm, now_ns)
  sm.alive["liveLocationKalman"] = True
  sm.logMonoTime["liveLocationKalman"] -= 1
  assert not local_localization_valid(sm, now_ns)
  sm.logMonoTime["liveLocationKalman"] = now_ns
  location.gpsOK = False
  assert not local_localization_valid(sm, now_ns)


def test_lane_control_inputs_require_seen_alive_and_valid():
  services = ("modelV2", "extrinsicsCalibration", "deviceState", "narrowRoadCameraState")
  sm = SimpleNamespace(
    seen=dict.fromkeys(services, True),
    alive=dict.fromkeys(services, True),
    valid=dict.fromkeys(services, True),
  )
  assert services_healthy(sm, services)
  for health in (sm.seen, sm.alive, sm.valid):
    health["modelV2"] = False
    assert not services_healthy(sm, services)
    health["modelV2"] = True


def test_track_hud_never_treats_seen_alone_as_service_health():
  hud = (ROOT / "selfdrive/ui/mici/onroad/hud_renderer.py").read_text()
  assert 'sm.alive["navAssistStateSP"] and sm.valid["navAssistStateSP"]' in hud
  assert 'ui_state.sm.alive["laneTopologyStateSP"] and ui_state.sm.valid["laneTopologyStateSP"]' in hud
  assert "CROSSING DATA VALID" in hud
  assert 'sm.alive["navLaneIntentSP"] and sm.valid["navLaneIntentSP"]' in hud
  assert "AMap推荐" in hud


class FakeParams:
  pass


def test_manager_receiver_requires_only_c3xl_while_control_observers_require_tesla(monkeypatch):
  tesla = SimpleNamespace(brand="tesla")
  monkeypatch.setattr(process_config, "get_hardware_profile", lambda: HardwareProfile.C3XL)
  configured = FakeParams()
  assert process_config.navassist_receiver_ready(False, configured, tesla)
  assert process_config.navassist_receiver_ready(True, configured, tesla)
  assert process_config.navassist_lane_observer_ready(True, configured, tesla)
  assert not process_config.navassist_lane_observer_ready(False, configured, tesla)
  honda = SimpleNamespace(brand="honda")
  assert process_config.navassist_receiver_ready(False, configured, honda)
  assert not process_config.navassist_lane_observer_ready(True, configured, honda)
  monkeypatch.setattr(process_config, "get_hardware_profile", lambda: HardwareProfile.STANDARD)
  assert not process_config.navassist_receiver_ready(True, configured, tesla)
