import json
import subprocess
import threading
import time

from openpilot.common.basedir import BASEDIR
from openpilot.common.hardware.usb import CHESTNUT_ROM_USB_IDS, CHESTNUT_USB_IDS, is_chestnut_runtime_device
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog


def parse_safe_poweroff_report(output: str) -> dict:
  for line in reversed(output.splitlines()):
    try:
      report = json.loads(line)
    except json.JSONDecodeError:
      continue
    if report.get("schema") != "ut3g-safe-f3-poweroff-v1":
      raise ValueError("unexpected F3 poweroff report schema")
    if report.get("safe_to_cut_external_power") is not True:
      raise ValueError("safe_to_cut_external_power was not confirmed")
    if report.get("persistent_writes") != 0:
      raise ValueError("persistent_writes was not zero")
    expected_f3_writes = {"f3-powered-off": 1, "already-not-l0": 0}.get(report.get("state"))
    if expected_f3_writes is None:
      raise ValueError("unexpected F3 poweroff state")
    if report.get("f3_writes") != expected_f3_writes:
      raise ValueError("F3 write count does not match poweroff state")
    return report
  raise ValueError("F3 poweroff script did not return a JSON report")


class ChestnutEjector:
  """Own asynchronous offroad link shutdown and manual detach requests."""
  LOW_SPEED_RECOVERY_DELAY = 3.0

  def __init__(self, params: Params):
    self.params = params
    self.thread: threading.Thread | None = None
    self.detached_seen = False
    self.auto_power_down_attempted = False
    self.low_speed_since: float | None = None
    self.low_speed_recovery_attempted = False

  def eject(self, *, automatic: bool = False) -> None:
    command = ["sudo", "env", f"PYTHONPATH={BASEDIR}/tinygrad_repo", "/usr/local/venv/bin/python", "-u",
               f"{BASEDIR}/tools/ut3g_safe_f3_poweroff.py"]
    if automatic:
      command.extend(("--wait-for-users", "--fast-release-after-f3"))
    ret = subprocess.run(command, cwd=BASEDIR,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    output = ret.stdout.strip()
    report_error = None
    if ret.returncode == 0:
      try:
        parse_safe_poweroff_report(output)
      except ValueError as exc:
        report_error = str(exc)

    if not automatic:
      if ret.returncode == 0 and report_error is None:
        self.params.put("UsbGpuEjectStatus", "safe")
        self.params.remove("UsbGpuEjectError")
      else:
        self.params.put("UsbGpuEjectStatus", "error")
        self.params.put("UsbGpuEjectError", report_error or output[-300:] or f"exit {ret.returncode}")
    cloudlog.event("chestnut eject done", returncode=ret.returncode, output=output[-1000:],
                   automatic=automatic, error=ret.returncode != 0 or report_error is not None)

  def _start(self, *, automatic: bool) -> None:
    self.thread = threading.Thread(target=self.eject, kwargs={"automatic": automatic}, daemon=True,
                                   name="chestnut-auto-power-down" if automatic else "chestnut-eject")
    self.thread.start()

  def recover_low_speed(self) -> None:
    if not self.params.get_bool("IsOffroad"):
      return
    command = ["sudo", "env", f"PYTHONPATH={BASEDIR}", "/usr/local/venv/bin/python", "-u",
               f"{BASEDIR}/openpilot/system/hardware/chestnut/eject.py", "--recover-low-speed"]
    ret = subprocess.run(command, cwd=BASEDIR,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    cloudlog.event("chestnut low-speed recovery done", returncode=ret.returncode,
                   output=ret.stdout.strip()[-1000:], error=ret.returncode != 0)

  def _start_low_speed_recovery(self) -> None:
    self.thread = threading.Thread(target=self.recover_low_speed, daemon=True,
                                   name="chestnut-low-speed-recovery")
    self.thread.start()

  def update(self, offroad: bool, usb_state: list[dict], *, auto_power_down: bool = False,
             recover_initial_low_speed: bool = False) -> None:
    detected = any((d["vendorId"], d["productId"]) in CHESTNUT_USB_IDS + CHESTNUT_ROM_USB_IDS for d in usb_state)
    runtime_detected = any(is_chestnut_runtime_device(d) for d in usb_state)
    ready = any(is_chestnut_runtime_device(d) and d.get("speedMbps", 0) == 5000 for d in usb_state)
    wake_capable_serials = self.params.get("ChestnutWakeCapableSerials") or []
    wake_capable = isinstance(wake_capable_serials, list) and any(
      is_chestnut_runtime_device(d) and d.get("serial", "") in wake_capable_serials for d in usb_state
    )
    status = self.params.get("UsbGpuEjectStatus")

    low_speed = runtime_detected and not ready
    if not (recover_initial_low_speed and offroad and self.params.get_bool("IsOffroad") and low_speed):
      self.low_speed_since = None
    elif self.low_speed_since is None:
      self.low_speed_since = time.monotonic()

    if not offroad or not runtime_detected:
      self.auto_power_down_attempted = False

    if status == "safe" and not detected:
      self.detached_seen = True
    elif ready and status == "safe" and self.detached_seen:
      self.params.remove("UsbGpuEjectStatus")
      self.detached_seen = False

    if self.params.get_bool("UsbGpuEjectRequest"):
      if not offroad:
        self.params.remove("UsbGpuEjectRequest")
        self.params.put("UsbGpuEjectStatus", "error")
        self.params.put("UsbGpuEjectError", "eGPU can only be ejected while offroad")
        return
      if self.thread is not None and self.thread.is_alive():
        return

      self.params.remove("UsbGpuEjectRequest")
      self.params.put("UsbGpuEjectStatus", "ejecting")
      self.params.remove("UsbGpuEjectError")
      self.auto_power_down_attempted = True
      self._start(automatic=False)
      return

    if (self.low_speed_since is not None and not self.low_speed_recovery_attempted and
        time.monotonic() - self.low_speed_since >= self.LOW_SPEED_RECOVERY_DELAY and
        (self.thread is None or not self.thread.is_alive())):
      self.low_speed_recovery_attempted = True
      self._start_low_speed_recovery()
      return

    if not (auto_power_down and wake_capable and offroad and self.params.get_bool("IsOffroad") and runtime_detected):
      return
    if self.auto_power_down_attempted or (self.thread is not None and self.thread.is_alive()):
      return

    self.auto_power_down_attempted = True
    self._start(automatic=True)
