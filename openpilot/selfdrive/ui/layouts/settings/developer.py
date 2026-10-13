from openpilot.common.params import Params
from openpilot.selfdrive.ui.widgets.ssh_key import ssh_key_item
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import button_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult

if gui_app.sunnypilot_ui():
  from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp as toggle_item

# Description constants
DESCRIPTIONS = {
  'enable_adb': tr_noop(
    "ADB (Android Debug Bridge) allows connecting to your device over USB or over the network. " +
    "See https://docs.comma.ai/how-to/connect-to-comma for more info."
  ),
  'ssh_key': tr_noop(
    "Warning: This grants SSH access to all public keys in your GitHub settings. Never enter a GitHub username " +
    "other than your own. A comma employee will NEVER ask you to add their GitHub username."
  ),
  'alpha_longitudinal': tr_noop(
    "<b>WARNING: sunnypilot longitudinal control is in alpha for this car and may disable Automatic Emergency Braking (AEB).</b><br><br>" +
    "On this car, sunnypilot defaults to the car's built-in ACC instead of sunnypilot's longitudinal control. " +
    "Enable this to switch to sunnypilot longitudinal control. " +
    "Enabling Experimental mode is recommended when enabling sunnypilot longitudinal control alpha. " +
    "Changing this setting will restart sunnypilot if the car is powered on."
  ),
}


def nav_assist_paired(params: Params) -> bool:
  pairing = params.get("NavAssistPairedApp")
  if not isinstance(pairing, dict):
    return False
  if isinstance(pairing.get("keyId"), str):
    return True
  apps = pairing.get("apps")
  return isinstance(apps, list) and any(isinstance(app, dict) and isinstance(app.get("keyId"), str) for app in apps)


def nav_assist_turn_signal_ready(params: Params) -> bool:
  return params.get_bool("TeslaTurnSignalValidation")


class DeveloperLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._is_release = False  # self._params.get_bool("IsReleaseBranch")

    # Build items and keep references for callbacks/state updates
    self._adb_toggle = toggle_item(
      lambda: tr("Enable ADB"),
      description=lambda: tr(DESCRIPTIONS["enable_adb"]),
      initial_state=self._params.get_bool("AdbEnabled"),
      callback=self._on_enable_adb,
      # the Accelerator Link holds the USB port that ADB needs
      enabled=lambda: ui_state.is_offroad() and not ui_state.adb_blocked,
    )

    # SSH enable toggle + SSH key management
    self._ssh_toggle = toggle_item(
      lambda: tr("Enable SSH"),
      description="",
      initial_state=self._params.get_bool("SshEnabled"),
      callback=self._on_enable_ssh,
    )
    self._ssh_keys = ssh_key_item(lambda: tr("SSH Keys"), description=lambda: tr(DESCRIPTIONS["ssh_key"]))

    self._joystick_toggle = toggle_item(
      lambda: tr("Joystick Debug Mode"),
      description="",
      initial_state=self._params.get_bool("JoystickDebugMode"),
      callback=self._on_joystick_debug_mode,
      enabled=ui_state.is_offroad,
    )

    self._long_maneuver_toggle = toggle_item(
      lambda: tr("Longitudinal Maneuver Mode"),
      description="",
      initial_state=self._params.get_bool("LongitudinalManeuverMode"),
      callback=self._on_long_maneuver_mode,
    )

    self._lat_maneuver_toggle = toggle_item(
      lambda: tr("Lateral Maneuver Mode"),
      description="",
      initial_state=self._params.get_bool("LateralManeuverMode"),
      callback=self._on_lat_maneuver_mode,
    )

    self._nav_assist_paired = nav_assist_paired(self._params)
    self._nav_assist_turn_signal_ready = nav_assist_turn_signal_ready(self._params)
    self._nav_assist_toggle = toggle_item(
      lambda: tr("Navigation Assist Auto Pairing"),
      description=lambda: (
        tr("Open TesNav to discover and pair automatically. First pairing is accepted only while offroad.") + "<br><br>" +
        (tr("TesNav is paired.") if self._nav_assist_paired else tr("Waiting for TesNav automatic pairing.")) + "<br>" +
        (tr("Tesla physical turn-signal capability is enabled.") if self._nav_assist_turn_signal_ready else
         tr("Tesla physical turn-signal capability is disabled; enable it offroad and restart before lane-change testing."))
      ),
      initial_state=self._nav_assist_paired,
      callback=lambda _state: None,
      enabled=False,
    )
    self._nav_assist_reset = button_item(
      lambda: tr("Reset TesNav Pairing"),
      button_text=lambda: tr("Reset"),
      description=lambda: tr("Offroad only. Close the old App first; the next valid TesNav App will pair automatically."),
      callback=self._on_nav_assist_pairing_reset,
      enabled=ui_state.is_offroad,
    )
    self._alpha_long_toggle = toggle_item(
      lambda: tr("sunnypilot Longitudinal Control (Alpha)"),
      description=lambda: tr(DESCRIPTIONS["alpha_longitudinal"]),
      initial_state=self._params.get_bool("AlphaLongitudinalEnabled"),
      callback=self._on_alpha_long_enabled,
      enabled=lambda: not ui_state.engaged,
    )

    self._ui_debug_toggle = toggle_item(
      lambda: tr("UI Debug Mode"),
      description="",
      initial_state=self._params.get_bool("ShowDebugInfo"),
      callback=self._on_enable_ui_debug,
    )
    self._on_enable_ui_debug(self._params.get_bool("ShowDebugInfo"))

    self._scroller = Scroller([
      self._adb_toggle,
      self._ssh_toggle,
      self._ssh_keys,
      self._joystick_toggle,
      self._long_maneuver_toggle,
      self._lat_maneuver_toggle,
      self._nav_assist_toggle,
      self._nav_assist_reset,
      self._alpha_long_toggle,
      self._ui_debug_toggle,
    ], line_separator=True, spacing=0)

    # Toggles should be not available to change in onroad state
    ui_state.add_offroad_transition_callback(self._update_toggles)

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()
    self._nav_assist_paired = nav_assist_paired(self._params)
    self._nav_assist_turn_signal_ready = nav_assist_turn_signal_ready(self._params)

    # Hide non-release toggles on release builds
    # TODO: we can do an onroad cycle, but alpha long toggle requires a deinit function to re-enable radar and not fault
    for item in (
      self._joystick_toggle, self._long_maneuver_toggle, self._lat_maneuver_toggle,
      self._nav_assist_toggle, self._alpha_long_toggle,
      self._nav_assist_reset,
    ):
      item.set_visible(not self._is_release)

    # CP gating
    if ui_state.CP is not None:
      alpha_avail = ui_state.CP.alphaLongitudinalAvailable
      if not alpha_avail or self._is_release:
        self._alpha_long_toggle.set_visible(False)
        self._params.remove("AlphaLongitudinalEnabled")
      else:
        self._alpha_long_toggle.set_visible(True)

      long_man_enabled = ui_state.has_longitudinal_control and ui_state.is_offroad()
      self._long_maneuver_toggle.action_item.set_enabled(long_man_enabled)
      self._lat_maneuver_toggle.action_item.set_enabled(ui_state.is_offroad())
      self._nav_assist_toggle.action_item.set_enabled(False)
      self._nav_assist_reset.action_item.set_enabled(ui_state.is_offroad())
    else:
      self._long_maneuver_toggle.action_item.set_enabled(False)
      self._lat_maneuver_toggle.action_item.set_enabled(False)
      self._nav_assist_toggle.action_item.set_enabled(False)
      self._nav_assist_reset.action_item.set_enabled(False)
      self._alpha_long_toggle.set_visible(False)

    # TODO: make a param control list item so we don't need to manage internal state as much here
    # refresh toggles from params to mirror external changes
    for key, item in (
      ("AdbEnabled", self._adb_toggle),
      ("SshEnabled", self._ssh_toggle),
      ("JoystickDebugMode", self._joystick_toggle),
      ("LongitudinalManeuverMode", self._long_maneuver_toggle),
      ("LateralManeuverMode", self._lat_maneuver_toggle),
      ("AlphaLongitudinalEnabled", self._alpha_long_toggle),
      ("ShowDebugInfo", self._ui_debug_toggle),
    ):
      item.action_item.set_state(self._params.get_bool(key))
    self._nav_assist_toggle.action_item.set_state(self._nav_assist_paired)

  def _on_enable_ui_debug(self, state: bool):
    self._params.put_bool("ShowDebugInfo", state, block=True)
    gui_app.set_show_touches(state)
    gui_app.set_show_fps(state)
    gui_app.set_show_mouse_coords(state)

  def _on_nav_assist_pairing_reset(self):
    def confirm_callback(result: DialogResult):
      if result == DialogResult.CONFIRM:
        self._params.put_bool("NavAssistPairingReset", True, block=True)
        self._nav_assist_toggle.action_item.set_state(False)

    dlg = ConfirmDialog(
      tr("Reset the paired TesNav App? Close the old App before continuing."),
      tr("Reset"),
      callback=confirm_callback,
    )
    gui_app.push_widget(dlg)

  def _on_enable_adb(self, state: bool):
    self._params.put_bool("AdbEnabled", state, block=True)

  def _on_enable_ssh(self, state: bool):
    self._params.put_bool("SshEnabled", state, block=True)

  def _on_joystick_debug_mode(self, state: bool):
    self._params.put_bool("JoystickDebugMode", state, block=True)
    self._params.put_bool("LongitudinalManeuverMode", False, block=True)
    self._long_maneuver_toggle.action_item.set_state(False)
    self._params.put_bool("LateralManeuverMode", False, block=True)
    self._lat_maneuver_toggle.action_item.set_state(False)

  def _on_long_maneuver_mode(self, state: bool):
    self._params.put_bool("LongitudinalManeuverMode", state, block=True)
    self._params.put_bool("JoystickDebugMode", False, block=True)
    self._joystick_toggle.action_item.set_state(False)
    self._params.put_bool("LateralManeuverMode", False, block=True)
    self._lat_maneuver_toggle.action_item.set_state(False)

  def _on_lat_maneuver_mode(self, state: bool):
    self._params.put_bool("LateralManeuverMode", state, block=True)
    self._params.put_bool("ExperimentalMode", False, block=True)
    self._params.put_bool("JoystickDebugMode", False, block=True)
    self._joystick_toggle.action_item.set_state(False)
    self._params.put_bool("LongitudinalManeuverMode", False, block=True)
    self._long_maneuver_toggle.action_item.set_state(False)

  def _on_alpha_long_enabled(self, state: bool):
    if state:
      def confirm_callback(result: DialogResult):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("AlphaLongitudinalEnabled", True, block=True)
          self._params.put_bool("OnroadCycleRequested", True, block=True)
          self._update_toggles()
        else:
          self._alpha_long_toggle.action_item.set_state(False)

      # show confirmation dialog
      content = (f"<h1>{self._alpha_long_toggle.title}</h1><br>" +
                 f"<p>{self._alpha_long_toggle.description}</p>")

      dlg = ConfirmDialog(content, tr("Enable"), rich=True, callback=confirm_callback)
      gui_app.push_widget(dlg)

    else:
      self._params.put_bool("AlphaLongitudinalEnabled", False, block=True)
      self._params.put_bool("OnroadCycleRequested", True, block=True)
      self._update_toggles()
