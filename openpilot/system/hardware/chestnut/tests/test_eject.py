import os
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from openpilot.system.hardware.chestnut import eject
from openpilot.system.hardware.chestnut.ejector import ChestnutEjector
from openpilot.common.basedir import BASEDIR


class FakeParams:
  def __init__(self, values=None):
    self.values = values or {}

  def get(self, key):
    return self.values.get(key)

  def get_bool(self, key):
    return bool(self.values.get(key))

  def put(self, key, value):
    self.values[key] = value

  def remove(self, key):
    self.values.pop(key, None)


@pytest.fixture
def chestnut_path(tmp_path, monkeypatch):
  path = tmp_path / "4-1"
  path.mkdir()
  (path / "remove").write_text("")
  monkeypatch.setattr(eject, "VBUS_PATH", str(tmp_path / "missing-vbus"))
  monkeypatch.setattr(eject, "find_runtime_chestnut", lambda: (str(path), ("3801", "0001"), "custom test-CLEAN"))
  monkeypatch.setattr(eject, "_wait_disconnected", lambda timeout=eject.DETACH_TIMEOUT: True)
  return path


def test_safe_eject_leaves_externally_powered_device_for_physical_unplug(chestnut_path, monkeypatch):
  read_fd, write_fd = os.pipe()
  os.close(write_fd)
  monkeypatch.setattr(eject, "claim_interface", lambda path: read_fd)

  assert not eject.safe_eject()
  assert (chestnut_path / "remove").read_text() == ""
  with pytest.raises(OSError):
    os.fstat(read_fd)


def test_safe_eject_does_not_detach_when_claim_fails(chestnut_path, monkeypatch):
  def busy(_):
    raise RuntimeError("chestnut is in use")

  monkeypatch.setattr(eject, "claim_interface", busy)
  with pytest.raises(RuntimeError, match="in use"):
    eject.safe_eject()
  assert (chestnut_path / "remove").read_text() == ""


def test_safe_eject_requires_connected_device(monkeypatch):
  monkeypatch.setattr(eject, "find_runtime_chestnut", lambda: (None, None, None))
  with pytest.raises(RuntimeError, match="not connected"):
    eject.safe_eject()


def test_wait_disconnected_allows_slow_c3xl_teardown(monkeypatch):
  clock = [0.0]

  monkeypatch.setattr(eject.time, "monotonic", lambda: clock[0])
  monkeypatch.setattr(eject.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
  monkeypatch.setattr(eject, "find_runtime_chestnut", lambda: (("/sys/4-1", None, None) if clock[0] < 8.0 else (None, None, None)))

  assert eject._wait_disconnected()


def test_low_speed_recovery_restores_vbus_and_verifies_superspeed(tmp_path, monkeypatch):
  vbus = tmp_path / "enable"
  vbus.write_text("1\n")
  state = {"connected": True, "speed": 12}

  def write_vbus(value):
    state["connected"] = value.strip() != "0"
    if state["connected"]:
      state["speed"] = 5000
    return len(value)

  monkeypatch.setattr(eject, "VBUS_PATH", str(vbus))
  monkeypatch.setattr(eject.Path, "write_text", lambda self, value: write_vbus(value) if self == vbus else len(value))
  monkeypatch.setattr(eject, "find_runtime_chestnut", lambda: (
    (str(tmp_path / "4-1"), None, None) if state["connected"] else (None, None, None)))
  monkeypatch.setattr(eject, "_runtime_speed_mbps", lambda: (
    (str(tmp_path / "4-1"), state["speed"]) if state["connected"] else (None, 0)))
  monkeypatch.setattr(eject.time, "sleep", lambda _: None)

  report = eject.recover_low_speed_link()

  assert report == {"state": "recovered", "disconnected": True, "speed_before": 12, "speed_after": 5000}
  assert state["connected"]


def test_low_speed_recovery_restores_vbus_when_disconnect_check_fails(tmp_path, monkeypatch):
  vbus = tmp_path / "enable"
  vbus.write_text("1\n")
  writes = []

  monkeypatch.setattr(eject, "VBUS_PATH", str(vbus))
  monkeypatch.setattr(eject, "_runtime_speed_mbps", lambda: (str(tmp_path / "3-1"), 12))
  monkeypatch.setattr(eject, "_wait_disconnected", lambda _: (_ for _ in ()).throw(RuntimeError("probe failed")))
  monkeypatch.setattr(eject.Path, "write_text", lambda self, value: writes.append(value) or len(value))

  with pytest.raises(RuntimeError, match="probe failed"):
    eject.recover_low_speed_link()

  assert writes == ["0\n", "1\n"]


def test_ejector_rejects_onroad_request():
  params = FakeParams({"UsbGpuEjectRequest": True})
  ejector = ChestnutEjector(params)

  ejector.update(False, [])

  assert params.get("UsbGpuEjectStatus") == "error"
  assert "offroad" in params.get("UsbGpuEjectError")
  assert not params.get_bool("UsbGpuEjectRequest")


def test_ejector_runs_project_f3_poweroff_script(monkeypatch):
  params = FakeParams()
  captured = {}
  report = {
    "schema": "ut3g-safe-f3-poweroff-v1",
    "state": "f3-powered-off",
    "f3_writes": 1,
    "persistent_writes": 0,
    "safe_to_cut_external_power": True,
  }

  def run(command, **kwargs):
    captured["command"] = command
    captured["kwargs"] = kwargs
    return SimpleNamespace(returncode=0, stdout=json.dumps(report))

  monkeypatch.setattr("openpilot.system.hardware.chestnut.ejector.subprocess.run", run)
  ChestnutEjector(params).eject()

  assert captured["command"] == [
    "sudo", "env", f"PYTHONPATH={BASEDIR}/tinygrad_repo", "/usr/local/venv/bin/python", "-u",
    f"{BASEDIR}/tools/ut3g_safe_f3_poweroff.py",
  ]
  assert params.get("UsbGpuEjectStatus") == "safe"
  assert params.get("UsbGpuEjectError") is None


def test_automatic_power_down_waits_for_users_without_changing_manual_status(monkeypatch):
  params = FakeParams()
  captured = {}
  report = {
    "schema": "ut3g-safe-f3-poweroff-v1",
    "state": "f3-powered-off",
    "f3_writes": 1,
    "persistent_writes": 0,
    "safe_to_cut_external_power": True,
  }

  def run(command, **kwargs):
    captured["command"] = command
    return SimpleNamespace(returncode=0, stdout=json.dumps(report))

  monkeypatch.setattr("openpilot.system.hardware.chestnut.ejector.subprocess.run", run)
  ChestnutEjector(params).eject(automatic=True)

  assert captured["command"][-3:] == [
    f"{BASEDIR}/tools/ut3g_safe_f3_poweroff.py", "--wait-for-users", "--fast-release-after-f3",
  ]
  assert params.get("UsbGpuEjectStatus") is None
  assert params.get("UsbGpuEjectError") is None


def test_offroad_runtime_device_starts_one_automatic_power_down(monkeypatch):
  params = FakeParams({"IsOffroad": True, "ChestnutWakeCapableSerials": ["wake-dock"]})
  ejector = ChestnutEjector(params)
  start = Mock()
  monkeypatch.setattr(ejector, "_start", start)
  present = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
              "product": "custom ed4e39b7-CLEAN", "speedMbps": 5000, "serial": "wake-dock"}]

  ejector.update(True, present, auto_power_down=True)
  ejector.update(True, present, auto_power_down=True)

  start.assert_called_once_with(automatic=True)
  assert ejector.auto_power_down_attempted
  assert params.get("UsbGpuEjectStatus") is None


def test_unknown_dock_keeps_power_on(monkeypatch):
  params = FakeParams({"IsOffroad": True, "ChestnutWakeCapableSerials": ["wake-dock"]})
  ejector = ChestnutEjector(params)
  start = Mock()
  monkeypatch.setattr(ejector, "_start", start)
  present = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
              "product": "custom ed4e39b7-CLEAN", "speedMbps": 5000, "serial": "always-on-dock"}]

  ejector.update(True, present, auto_power_down=True)
  ejector.update(True, [{k: v for k, v in present[0].items() if k != "serial"}], auto_power_down=True)

  start.assert_not_called()
  assert not ejector.auto_power_down_attempted


def test_switching_docks_selects_registered_power_policy(monkeypatch):
  params = FakeParams({"IsOffroad": True, "ChestnutWakeCapableSerials": ["wake-dock"]})
  ejector = ChestnutEjector(params)
  start = Mock()
  monkeypatch.setattr(ejector, "_start", start)
  device = {"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
            "product": "custom ed4e39b7-CLEAN", "speedMbps": 5000}

  ejector.update(True, [{**device, "serial": "always-on-dock"}], auto_power_down=True)
  ejector.update(True, [], auto_power_down=True)
  ejector.update(True, [{**device, "serial": "wake-dock"}], auto_power_down=True)

  start.assert_called_once_with(automatic=True)


def test_initial_offroad_does_not_automatically_power_down(monkeypatch):
  params = FakeParams({"IsOffroad": True})
  ejector = ChestnutEjector(params)
  start = Mock()
  monkeypatch.setattr(ejector, "_start", start)
  present = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
              "product": "custom ed4e39b7-CLEAN", "speedMbps": 5000}]

  ejector.update(True, present, auto_power_down=False)

  start.assert_not_called()


def test_initial_low_speed_recovery_requires_stable_offroad_state(monkeypatch):
  params = FakeParams({"IsOffroad": True})
  ejector = ChestnutEjector(params)
  start = Mock()
  clock = [10.0]
  monkeypatch.setattr(ejector, "_start_low_speed_recovery", start)
  monkeypatch.setattr("openpilot.system.hardware.chestnut.ejector.time.monotonic", lambda: clock[0])
  slow = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
           "product": "custom ed4e39b7-CLEAN", "speedMbps": 12}]

  ejector.update(True, slow, recover_initial_low_speed=True)
  clock[0] += ejector.LOW_SPEED_RECOVERY_DELAY - 0.1
  ejector.update(True, slow, recover_initial_low_speed=True)
  start.assert_not_called()

  clock[0] += 0.1
  ejector.update(True, slow, recover_initial_low_speed=True)
  ejector.update(True, slow, recover_initial_low_speed=True)

  start.assert_called_once_with()
  assert ejector.low_speed_recovery_attempted


def test_initial_low_speed_recovery_does_not_run_onroad_or_at_superspeed(monkeypatch):
  params = FakeParams({"IsOffroad": True})
  ejector = ChestnutEjector(params)
  start = Mock()
  monkeypatch.setattr(ejector, "_start_low_speed_recovery", start)
  monkeypatch.setattr(ejector, "LOW_SPEED_RECOVERY_DELAY", 0.0)
  slow = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
           "product": "custom ed4e39b7-CLEAN", "speedMbps": 12}]
  ready = [{**slow[0], "speedMbps": 5000}]

  ejector.update(False, slow, recover_initial_low_speed=True)
  ejector.update(True, ready, recover_initial_low_speed=True)
  params.values["IsOffroad"] = False
  ejector.update(True, slow, recover_initial_low_speed=True)

  start.assert_not_called()


def test_low_speed_worker_rechecks_offroad_and_uses_project_pythonpath(monkeypatch):
  params = FakeParams({"IsOffroad": True})
  captured = {}

  def run(command, **kwargs):
    captured["command"] = command
    return SimpleNamespace(returncode=0, stdout='{"state":"recovered"}\n')

  monkeypatch.setattr("openpilot.system.hardware.chestnut.ejector.subprocess.run", run)
  ejector = ChestnutEjector(params)
  ejector.recover_low_speed()

  assert captured["command"] == [
    "sudo", "env", f"PYTHONPATH={BASEDIR}", "/usr/local/venv/bin/python", "-u",
    f"{BASEDIR}/openpilot/system/hardware/chestnut/eject.py", "--recover-low-speed",
  ]

  params.values["IsOffroad"] = False
  captured.clear()
  ejector.recover_low_speed()
  assert captured == {}


def test_manual_eject_remains_available_before_first_onroad(monkeypatch):
  params = FakeParams({"IsOffroad": True, "UsbGpuEjectRequest": True})
  ejector = ChestnutEjector(params)
  start = Mock()
  monkeypatch.setattr(ejector, "_start", start)
  present = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
              "product": "custom ed4e39b7-CLEAN", "speedMbps": 5000}]

  ejector.update(True, present, auto_power_down=False)

  start.assert_called_once_with(automatic=False)
  assert not params.get_bool("UsbGpuEjectRequest")
  assert params.get("UsbGpuEjectStatus") == "ejecting"


def test_automatic_power_down_does_not_block_hardwared_update(monkeypatch):
  params = FakeParams({"IsOffroad": True, "ChestnutWakeCapableSerials": ["wake-dock"]})
  ejector = ChestnutEjector(params)
  entered = threading.Event()
  release = threading.Event()
  present = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
              "product": "custom ed4e39b7-CLEAN", "speedMbps": 5000, "serial": "wake-dock"}]

  def block_in_worker(*, automatic):
    assert automatic
    entered.set()
    release.wait(1)

  monkeypatch.setattr(ejector, "eject", block_in_worker)
  ejector.update(True, present, auto_power_down=True)

  assert entered.wait(0.5)
  assert ejector.thread is not None and ejector.thread.is_alive()
  release.set()
  ejector.thread.join(1)


def test_automatic_power_down_rearms_after_disconnect(monkeypatch):
  params = FakeParams({"IsOffroad": True, "ChestnutWakeCapableSerials": ["wake-dock"]})
  ejector = ChestnutEjector(params)
  start = Mock()
  monkeypatch.setattr(ejector, "_start", start)
  present = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
              "product": "custom ed4e39b7-CLEAN", "speedMbps": 5000, "serial": "wake-dock"}]

  ejector.update(True, present, auto_power_down=True)
  ejector.update(True, [], auto_power_down=True)
  ejector.update(True, present, auto_power_down=True)

  assert start.call_args_list == [call(automatic=True), call(automatic=True)]


def test_automatic_power_down_requires_manager_offroad_confirmation(monkeypatch):
  params = FakeParams({"ChestnutWakeCapableSerials": ["wake-dock"]})
  ejector = ChestnutEjector(params)
  start = Mock()
  monkeypatch.setattr(ejector, "_start", start)
  present = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
              "product": "custom ed4e39b7-CLEAN", "speedMbps": 5000, "serial": "wake-dock"}]

  ejector.update(True, present, auto_power_down=True)
  start.assert_not_called()

  params.values["IsOffroad"] = True
  ejector.update(True, present, auto_power_down=True)
  start.assert_called_once_with(automatic=True)


def test_ejector_rejects_success_exit_without_safe_f3_report(monkeypatch):
  params = FakeParams()
  report = {
    "schema": "ut3g-safe-f3-poweroff-v1",
    "state": "f3-powered-off",
    "f3_writes": 1,
    "persistent_writes": 0,
    "safe_to_cut_external_power": False,
  }
  ret = SimpleNamespace(returncode=0, stdout=json.dumps(report))
  monkeypatch.setattr("openpilot.system.hardware.chestnut.ejector.subprocess.run", lambda *args, **kwargs: ret)

  ChestnutEjector(params).eject()

  assert params.get("UsbGpuEjectStatus") == "error"
  assert "safe_to_cut_external_power" in params.get("UsbGpuEjectError")


def test_ejector_rejects_report_with_persistent_writes(monkeypatch):
  params = FakeParams()
  report = {
    "schema": "ut3g-safe-f3-poweroff-v1",
    "state": "f3-powered-off",
    "f3_writes": 1,
    "persistent_writes": 1,
    "safe_to_cut_external_power": True,
  }
  ret = SimpleNamespace(returncode=0, stdout=json.dumps(report))
  monkeypatch.setattr("openpilot.system.hardware.chestnut.ejector.subprocess.run", lambda *args, **kwargs: ret)

  ChestnutEjector(params).eject()

  assert params.get("UsbGpuEjectStatus") == "error"
  assert "persistent_writes" in params.get("UsbGpuEjectError")


def test_ejector_rejects_unknown_poweroff_state(monkeypatch):
  params = FakeParams()
  report = {
    "schema": "ut3g-safe-f3-poweroff-v1",
    "state": "unknown",
    "f3_writes": 0,
    "persistent_writes": 0,
    "safe_to_cut_external_power": True,
  }
  ret = SimpleNamespace(returncode=0, stdout=json.dumps(report))
  monkeypatch.setattr("openpilot.system.hardware.chestnut.ejector.subprocess.run", lambda *args, **kwargs: ret)

  ChestnutEjector(params).eject()

  assert params.get("UsbGpuEjectStatus") == "error"
  assert "state" in params.get("UsbGpuEjectError")


def test_safe_status_clears_only_after_disconnect_and_5gbps_return():
  params = FakeParams({"UsbGpuEjectStatus": "safe"})
  ejector = ChestnutEjector(params)
  present = [{"vendorId": 0x3801, "productId": 0x0001, "manufacturer": "tiny",
              "product": "custom ed4e39b7-CLEAN", "speedMbps": 5000}]

  ejector.update(True, present)
  assert params.get("UsbGpuEjectStatus") == "safe"

  ejector.update(True, [])
  ejector.update(True, [{**present[0], "speedMbps": 480}])
  assert params.get("UsbGpuEjectStatus") == "safe"

  ejector.update(True, present)
  assert params.get("UsbGpuEjectStatus") is None


def test_disconnect_never_overrides_missing_safe_f3_report(monkeypatch):
  params = FakeParams()
  ejector = ChestnutEjector(params)
  ret = SimpleNamespace(returncode=eject.DETACH_PENDING_EXIT_CODE, stdout="eGPU detach is still pending")
  monkeypatch.setattr("openpilot.system.hardware.chestnut.ejector.subprocess.run", lambda *args, **kwargs: ret)

  ejector.eject()
  assert params.get("UsbGpuEjectStatus") == "error"

  ejector.update(True, [])
  assert params.get("UsbGpuEjectStatus") == "error"
  assert params.get("UsbGpuEjectError") == "eGPU detach is still pending"


def test_non_pending_error_does_not_converge_to_safe(monkeypatch):
  params = FakeParams()
  ejector = ChestnutEjector(params)
  ret = SimpleNamespace(returncode=1, stdout="permission denied")
  monkeypatch.setattr("openpilot.system.hardware.chestnut.ejector.subprocess.run", lambda *args, **kwargs: ret)

  ejector.eject()
  ejector.update(True, [])

  assert params.get("UsbGpuEjectStatus") == "error"
  assert params.get("UsbGpuEjectError") == "permission denied"


def test_cli_marks_slow_detach_as_temporary_failure(monkeypatch):
  monkeypatch.setattr(eject, "safe_eject", lambda: (_ for _ in ()).throw(eject.DetachPendingError("pending")))
  monkeypatch.setattr(eject.sys, "argv", ["eject.py"])

  assert eject.main() == eject.DETACH_PENDING_EXIT_CODE
