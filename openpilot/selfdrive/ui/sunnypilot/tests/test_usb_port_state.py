"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The comma's USB-C CC pin, as ui_state's params pass tracks it: the port comes
up as soon as the pin says a host is there, and one settle window later, with
neither the bus nor jetlink naming what is on it, it is "unknown" and the mici
home shows the generic usb icon. The one-shot decision is the source branch's:
a chestnut arriving late is a separate clear (UIStateSP.update_params), and a
disconnect clears everything.

The bus itself is real here: the pass's sysfs readers are patched, not the
adapter, so is_chestnut_usb_id() runs as it does on the device.
"""
import os
import unittest
from unittest import mock

os.environ["BIG"] = "0"
os.environ.setdefault("SCALE", "1")

from openpilot.common.prefix import OpenpilotPrefix
from openpilot.common.test import OpenpilotTestCase

# the window's own params, for whatever it reads while it comes up; every test
# then runs under its own prefix
_window_prefix = OpenpilotPrefix()

# what get_usb_state() hands over: a running chestnut, one in its ROM
# bootloader, and a host's device that is no accelerator at all
CHESTNUT_RUNNING = {"vendorId": 0xADD1, "productId": 0x0001, "product": "custom ed4e39b7-CLEAN", "manufacturer": "tiny"}
CHESTNUT_ROM = {"vendorId": 0x174C, "productId": 0x2463, "product": "USB 3.2 PCIe TinyEnclosure", "manufacturer": "ASMedia"}
NOT_AN_ACCELERATOR = {"vendorId": 0x05AC, "productId": 0x12A8, "product": "iPhone", "manufacturer": "Apple"}


def setUpModule():
  """A hidden raylib window, once for the module: ui_state builds widgets."""
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  _window_prefix.__enter__()
  rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
  gui_app.init_window("test_usb_port_state", fps=30)


def tearDownModule():
  from openpilot.system.ui.lib.application import gui_app
  gui_app.close()
  _window_prefix.__exit__(None, None, None)


def ui_state_module():
  """The module, not the singleton that shares its name."""
  import openpilot.selfdrive.ui.ui_state as module
  return module


def snapshot(**fields):
  """jetlink's snapshot, nothing to show unless a field says so."""
  from jetlink.openpilot import Status
  values = {'enabled': False, 'mode': 'off', 'transport': 'USB', 'present': False, 'port': None, 'ready': False,
            'reason': None, 'progress': None, 'model': None, 'default_model': None}
  if fields.get('enabled'):
    values['mode'] = 'usb'
  values.update(fields)
  return Status(**values)


class USBPortTestCase(OpenpilotTestCase):
  """ui_state with a plugged-out port, and one params pass at a time."""

  def setUp(self):
    super().setUp()
    from openpilot.common.params import Params
    from openpilot.selfdrive.ui.ui_state import ui_state
    self.ui_state = ui_state
    ui_state.params = Params()
    self.unplugged()

  def unplugged(self):
    self.ui_state.usb_connected = False
    self.ui_state.usb_connected_ts = None
    self.ui_state.usb_disconnected_ts = None
    self.ui_state.usb_unknown = False
    self.ui_state.jetlink = None

  def params_pass(self, now, cc_connected, devices=(), jetlink=None):
    """One 5 Hz params pass: the CC pin and the bus as given, the clock frozen."""
    fake_time = mock.MagicMock()
    fake_time.monotonic.return_value = now
    with mock.patch.object(ui_state_module(), "time", fake_time), \
         mock.patch.object(ui_state_module(), "read_int", return_value=1 if cc_connected else 0), \
         mock.patch.object(ui_state_module(), "get_usb_state", return_value=list(devices)), \
         mock.patch("openpilot.sunnypilot.jetlink_adapter.status", return_value=jetlink):
      self.ui_state.update_params()


class USBPortTrackingTest(USBPortTestCase):
  def test_a_quiet_port_is_not_connected(self):
    self.params_pass(0.0, cc_connected=False)
    assert not self.ui_state.usb_connected
    assert not self.ui_state.usb_unknown

  def test_a_host_on_the_cable_connects_at_once(self):
    self.params_pass(0.0, cc_connected=True)
    assert self.ui_state.usb_connected
    assert not self.ui_state.usb_unknown

  def test_an_unnamed_device_is_unknown_when_the_settle_window_expires(self):
    self.params_pass(0.0, cc_connected=True)
    # the gadget needs a moment: within the window nothing is claimed
    self.params_pass(5.0, cc_connected=True, devices=[NOT_AN_ACCELERATOR])
    assert self.ui_state.usb_connected
    assert not self.ui_state.usb_unknown

    self.params_pass(10.5, cc_connected=True, devices=[NOT_AN_ACCELERATOR])
    assert self.ui_state.usb_unknown

  def test_a_chestnut_on_the_bus_names_the_port(self):
    # the running board, and the board in its ROM bootloader: the same ids the
    # ejector counts as detected, the bootloader ones only when asked for
    for device in (CHESTNUT_RUNNING, CHESTNUT_ROM):
      with self.subTest(product=device["product"]):
        self.unplugged()
        self.params_pass(0.0, cc_connected=True)
        self.params_pass(10.5, cc_connected=True, devices=[device])
        assert not self.ui_state.usb_unknown

  def test_jetlink_naming_the_port_is_enough(self):
    # what the link shows is a device the UI can name, whether it is on the
    # gadget, provisioning, or merely switched on
    for view in (snapshot(enabled=True, present=True), snapshot(present=True),
                 snapshot(progress={'stage': 'build', 'frac': 0.2, 'msg': 'building the model'})):
      with self.subTest(view=view):
        self.unplugged()
        # the decision reads the snapshot the previous pass left, so the view
        # has to be one pass old by the time the settle window expires
        self.params_pass(0.0, cc_connected=True, jetlink=view)
        self.params_pass(10.5, cc_connected=True, devices=[NOT_AN_ACCELERATOR], jetlink=view)
        assert not self.ui_state.usb_unknown

  def test_the_decision_is_taken_once_per_plug(self):
    # the source's one-shot: the settle window expires once, and a board that
    # enumerates after it does not re-open the question
    self.params_pass(0.0, cc_connected=True)
    self.params_pass(10.5, cc_connected=True, devices=[NOT_AN_ACCELERATOR])
    assert self.ui_state.usb_unknown

    self.params_pass(20.0, cc_connected=True, devices=[CHESTNUT_RUNNING])
    assert self.ui_state.usb_unknown

  def test_a_late_gadget_clears_the_flag(self):
    # the Jetson configures its gadget seconds after a cold boot, after the
    # decision: the params pass clears "unknown" when jetlink sees it
    self.params_pass(0.0, cc_connected=True)
    self.params_pass(10.5, cc_connected=True, devices=[NOT_AN_ACCELERATOR])
    assert self.ui_state.usb_unknown

    self.params_pass(30.0, cc_connected=True, devices=[NOT_AN_ACCELERATOR],
                     jetlink=snapshot(enabled=True, present=True))
    assert self.ui_state.usb_connected
    assert not self.ui_state.usb_unknown

  def test_a_disconnect_clears_everything(self):
    self.params_pass(0.0, cc_connected=True)
    self.params_pass(10.5, cc_connected=True, devices=[NOT_AN_ACCELERATOR])
    assert self.ui_state.usb_unknown

    # one low sample is not yet a disconnect: the pin is read on a 5 Hz tick
    self.params_pass(11.0, cc_connected=False)
    assert self.ui_state.usb_connected and self.ui_state.usb_unknown

    self.params_pass(11.5, cc_connected=False)
    assert not self.ui_state.usb_connected
    assert not self.ui_state.usb_unknown


class MiciHomeUSBIconTest(USBPortTestCase):
  """The icon the flag drives: the eGPU pair still speaks for what the branch
  can name, so only the unnamed port device takes the generic usb icon."""

  def setUp(self):
    super().setUp()
    import pyray as rl
    from openpilot.selfdrive.ui.mici.layouts.home import MiciHomeLayout
    self.layout = MiciHomeLayout()
    self.layout.set_rect(rl.Rectangle(0, 0, 1000, 600))

  def render(self, connected, unknown):
    self.ui_state.usb_connected = connected
    self.ui_state.usb_unknown = unknown
    self.layout._render(0)
    return self.layout._usb_icon.is_visible

  def test_the_usb_icon_shows_exactly_for_an_unnamed_device(self):
    assert not self.render(connected=False, unknown=False)
    assert not self.render(connected=True, unknown=False)
    assert self.render(connected=True, unknown=True)
    assert not self.render(connected=False, unknown=True)


if __name__ == "__main__":
  unittest.main()
