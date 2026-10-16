"""The onroad accelerator indicator: what it says, when it shows, and what the
user is meant to read off it. The model is pure, so the wording and the levels
are pinned here; one case draws it in a hidden window so a raylib call that
cannot run is caught here and not on a drive."""
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("BIG", "0")
os.environ.setdefault("SCALE", "1")

import pyray as rl
import pytest

from openpilot.system.ui.lib.multilang import tr
from openpilot.selfdrive.ui.onroad.accelerator_indicator import (
  JOINING,
  READY,
  RETRYING,
  RUNNING,
  UNAVAILABLE,
  AcceleratorStatus,
  accelerator_indicator_style,
  build_accelerator_status,
  bundle_model_name,
  draw_accelerator_indicator,
  indicator_colors,
  indicator_pill_width,
  should_show_accelerator_indicator,
)


def setUpModule():
  """A hidden raylib window, once for the module: the drawing cases need a
  render context and the loaded fonts."""
  from openpilot.common.prefix import OpenpilotPrefix
  from openpilot.system.ui.lib.application import gui_app
  global _window_prefix
  _window_prefix = OpenpilotPrefix()
  _window_prefix.__enter__()
  rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
  gui_app.init_window("test_accelerator_indicator", fps=30)


def tearDownModule():
  from openpilot.system.ui.lib.application import gui_app
  gui_app.close()
  _window_prefix.__exit__(None, None, None)


_window_prefix = None


def _fake_view(**fields):
  values = {"enabled": False, "present": False, "model": None, "default_model": None, "ready": False}
  values.update(fields)
  return SimpleNamespace(**values)


def _fake_ui_state(**fields):
  values = {
    "started": True,
    "chestnut_present": False,
    "chestnut_state": None,
    "active_bundle": None,
    "jetlink_view": None,
    "_accelerator_state_name": "none",
  }
  values.update(fields)
  return SimpleNamespace(**values)


# -- the gate ------------------------------------------------------------------

def test_a_drive_with_the_link_off_and_nothing_published_shows_nothing():
  """No accelerator in play, no pill: the row must not take screen space on
  every ordinary drive."""
  assert not should_show_accelerator_indicator(
    started=True, chestnut_present=False, link_mode="off",
    jetlink_enabled=False, jetlink_present=False, state="none")


def test_an_accelerator_that_publishes_a_state_shows_even_if_the_params_snapshot_is_stale():
  for state in ("joining", "ready", "running", "retrying"):
    assert should_show_accelerator_indicator(
      started=True, chestnut_present=False, link_mode="off",
      jetlink_enabled=False, jetlink_present=False, state=state)


def test_the_link_on_or_a_live_far_end_shows_even_before_any_state():
  assert should_show_accelerator_indicator(
    started=True, chestnut_present=False, link_mode="usb",
    jetlink_enabled=True, jetlink_present=False, state="none")
  assert should_show_accelerator_indicator(
    started=True, chestnut_present=False, link_mode="off",
    jetlink_enabled=False, jetlink_present=True, state="none")


def test_offroad_and_a_fitted_chestnut_are_quiet():
  assert not should_show_accelerator_indicator(
    started=False, chestnut_present=False, link_mode="usb",
    jetlink_enabled=True, jetlink_present=True, state="running")
  assert not should_show_accelerator_indicator(
    started=True, chestnut_present=True, link_mode="usb",
    jetlink_enabled=True, jetlink_present=True, state="running")


# -- the four states the user has to tell apart --------------------------------

def test_each_accelerator_state_has_its_own_level():
  assert build_accelerator_status(state="running").level == RUNNING
  assert build_accelerator_status(state="ready").level == READY
  assert build_accelerator_status(state="joining").level == JOINING
  assert build_accelerator_status(state="retrying").level == RETRYING
  assert build_accelerator_status(state="unavailable").level == UNAVAILABLE


def test_running_and_ready_do_not_read_alike():
  """The whole point of the row: 'the large model drives' and 'the large model
  is loaded and never gets a window' must not be the same picture."""
  running = build_accelerator_status(state="running")
  ready = build_accelerator_status(state="ready")
  assert running.headline != ready.headline
  assert running.detail != ready.detail
  # the same source strings the module translates, so this holds in any language
  assert running.headline == tr("Large model is driving")
  assert ready.headline == tr("Large model is ready")
  assert running.level == RUNNING and ready.level == READY


def test_running_is_green_and_the_waiting_states_are_not():
  running = indicator_colors(RUNNING, 1.0)
  for level in (READY, JOINING, RETRYING, UNAVAILABLE):
    other = indicator_colors(level, 1.0)
    assert running != other
  # green: the headline channel dominates and red is low
  headline = running[0]
  assert headline.g > 180 and headline.r < 140


def test_the_joining_pill_breathes_and_ready_does_not():
  """A join that never lands has to look alive but different from a solid
  ready, or a driver cannot tell 'working' from 'stuck'."""
  dim = indicator_colors(JOINING, 0.4)
  bright = indicator_colors(JOINING, 1.0)
  assert dim[0].a < bright[0].a
  # ready ignores the pulse ballast at the same value
  assert indicator_colors(READY, 0.4)[0].a < indicator_colors(READY, 1.0)[0].a
  # the fill stays readable at the dimmest pulse
  assert dim[3].a >= 150


def test_a_state_this_build_does_not_know_is_shown_not_hidden():
  status = build_accelerator_status(state="teleporting")
  assert status.visible and status.level == UNAVAILABLE
  assert "teleporting" in status.detail


def test_nothing_published_yet_says_the_small_model_is_driving():
  status = build_accelerator_status(state="none")
  assert status.visible
  assert status.headline != build_accelerator_status(state="running").headline
  assert status.level == "initializing"


def test_hidden_status_has_nothing_to_draw():
  status = build_accelerator_status(state="running", visible=False)
  assert status == AcceleratorStatus(False, "", "", "")


# -- the model name, so both ends can be compared ------------------------------

def test_the_pick_names_the_model():
  assert build_accelerator_status(state="running", model_name="CTV3M").model == "CTV3M"
  assert build_accelerator_status(state="running").model != ""


def test_the_links_own_default_names_it_when_no_pick_is_stored():
  view = _fake_view(enabled=True, model="Cinque Terre")
  assert build_accelerator_status(state="ready", jetlink_view=view).model == "Cinque Terre"
  view = _fake_view(enabled=True, default_model="CTV3M")
  assert build_accelerator_status(state="ready", jetlink_view=view).model == "CTV3M"


def test_a_pick_beats_the_links_default():
  view = _fake_view(enabled=True, model="Cinque Terre", default_model="CTV3M")
  assert build_accelerator_status(state="running", model_name="My Model", jetlink_view=view).model == "My Model"


def test_a_bundle_is_named_from_either_shape_it_arrives_in():
  assert bundle_model_name({"displayName": "CTV3M", "internalName": "internal"}) == "CTV3M"
  assert bundle_model_name({"internalName": "internal"}) == "internal"
  assert bundle_model_name(SimpleNamespace(displayName="CTV3M")) == "CTV3M"
  assert bundle_model_name(None) == ""


# -- reading ui_state ----------------------------------------------------------

def _status_with(**fields):
  """accelerator_status() over a fake ui_state: the reader the HUD calls."""
  import openpilot.selfdrive.ui.onroad.accelerator_indicator as module
  fake = _fake_ui_state(**fields)
  with mock.patch("openpilot.selfdrive.ui.ui_state.ui_state", fake), \
       mock.patch("openpilot.selfdrive.ui.sunnypilot.accelerator_link.link_mode",
                  lambda: fields.get("link_mode", "off")):
    return module.accelerator_status()


def test_reading_ui_state_gives_the_state_the_modeld_publishes():
  status = _status_with(_accelerator_state_name="running", active_bundle={"displayName": "CTV3M"},
                        link_mode="usb")
  assert status.visible and status.level == RUNNING and status.model == "CTV3M"


def test_reading_ui_state_stays_quiet_on_an_ordinary_drive():
  status = _status_with(_accelerator_state_name="none", link_mode="off")
  assert not status.visible


def test_a_fitted_chestnut_stays_quiet_through_the_full_reader():
  status = _status_with(chestnut_present=True, _accelerator_state_name="running", link_mode="usb")
  assert not status.visible


# -- the drawing ---------------------------------------------------------------

def test_the_style_sits_in_the_lower_left_clear_of_the_corner_widgets():
  """The pill moved from under MAX to the lower left. What is down there has
  to be cleared: the torque bar's arc (leftmost pixel x=669, topmost y=813 at
  full lock on the comma 3X), the developer UI's bottom bar (y=1019..1080,
  full width) and the rocket-fuel strip along the left edge (x=0..28)."""
  style = accelerator_indicator_style()
  height = style.line_height * 2 + style.padding
  foot = 1080 - style.bottom_margin
  # in the lower half, not under MAX (which is y=45..249) any more
  assert foot > 1080 * 0.5
  # clear of the torque bar's arc, which tops out at y=813...
  assert foot < 813
  # ...and of the developer UI's bottom bar, which is below the pill
  assert foot <= 1080 - 61
  # the left margin clears the rocket-fuel strip and keeps the MAX box's column
  assert style.left_margin >= 28
  # the foot is the pill's bottom edge, so the margin has to hold it
  assert style.bottom_margin >= height


def test_the_pill_is_wide_enough_for_whichever_line_is_longer():
  """The detail row carries the model's name and a sentence; sized from the
  headline alone it ran out of the pill, which the corner cannot afford."""
  style = accelerator_indicator_style()
  assert indicator_pill_width(style, 100.0, 400.0) == int(400.0) + style.padding * 2
  assert indicator_pill_width(style, 500.0, 100.0) == int(500.0) + style.padding * 2
  # and never narrower than the floor, however short the words
  assert indicator_pill_width(style, 1.0, 1.0) == style.min_width


def test_drawing_every_level_does_not_raise():
  import openpilot.selfdrive.ui.onroad.accelerator_indicator as module
  from openpilot.system.ui.lib.application import gui_app, FontWeight
  font = gui_app.font(FontWeight.MEDIUM)
  font_bold = gui_app.font(FontWeight.SEMI_BOLD)
  rect = rl.Rectangle(0, 0, 2160, 1080)
  for state in ("running", "ready", "joining", "retrying", "unavailable", "none"):
    fake = _fake_ui_state(_accelerator_state_name=state, active_bundle={"displayName": "CTV3M"},
                          link_mode="usb")
    with mock.patch("openpilot.selfdrive.ui.ui_state.ui_state", fake), \
         mock.patch("openpilot.selfdrive.ui.sunnypilot.accelerator_link.link_mode", lambda: "usb"):
      module.draw_accelerator_indicator(rect, font, font_bold, pulse=0.7)
  assert rect.width > 0


def test_drawing_a_hidden_status_touches_nothing():
  import openpilot.selfdrive.ui.onroad.accelerator_indicator as module
  from openpilot.system.ui.lib.application import gui_app, FontWeight
  font = gui_app.font(FontWeight.MEDIUM)
  fake = _fake_ui_state(_accelerator_state_name="none", link_mode="off")
  with mock.patch("openpilot.selfdrive.ui.ui_state.ui_state", fake), \
       mock.patch("openpilot.selfdrive.ui.sunnypilot.accelerator_link.link_mode", lambda: "off"), \
       mock.patch.object(module, "accelerator_status",
                         return_value=AcceleratorStatus(False, "", "", "")) as status, \
       mock.patch("openpilot.system.ui.lib.text_measure.measure_text_cached",
                  side_effect=AssertionError("measured a hidden row")):
    module.draw_accelerator_indicator(rl.Rectangle(0, 0, 2160, 1080), font, font, pulse=1.0)
  assert status.called


# -- the HUD draws it -----------------------------------------------------------

def _hud():
  """A HudRenderer with only what the drawing path reads: the fonts and the
  experiment button are built by __init__, which needs a window and a
  SubMaster; the row only needs the fonts."""
  from openpilot.selfdrive.ui.onroad.hud_renderer import HudRenderer
  from openpilot.system.ui.lib.application import gui_app, FontWeight
  hud = SimpleNamespace(_font_medium=gui_app.font(FontWeight.MEDIUM),
                        _font_semi_bold=gui_app.font(FontWeight.SEMI_BOLD),
                        _font_bold=gui_app.font(FontWeight.BOLD),
                        _exp_button=SimpleNamespace(render=lambda *a, **k: None),
                        is_cruise_available=False, is_cruise_set=False, set_speed=255,
                        speed=0.0, v_ego_cluster_seen=False, status=None)
  for name in ("_draw_accelerator_state", "_render", "_draw_set_speed", "_draw_current_speed",
               "_draw_egpu_icon"):
    setattr(hud, name, getattr(HudRenderer, name).__get__(hud))
  return hud


def test_the_hud_calls_the_indicator_it_wired_in():
  import openpilot.selfdrive.ui.onroad.hud_renderer as hud_renderer
  hud = _hud()
  seen = []
  with mock.patch.object(hud_renderer, "draw_accelerator_indicator", lambda *a, **k: seen.append(k)):
    hud._render(rl.Rectangle(0, 0, 2160, 1080))
  assert len(seen) == 1 and seen[0]["pulse"] == 1.0


def test_only_a_join_pulses_and_a_running_model_never_does():
  """pulse is the caller's side: one state name has to breathe, the rest are
  steady, or the pill cannot be read at a glance."""
  import openpilot.selfdrive.ui.onroad.hud_renderer as hud_renderer
  hud = _hud()
  pulses = []
  for state in ("running", "ready", "unavailable", "joining"):
    fake = _fake_ui_state(_accelerator_state_name=state)
    with mock.patch.object(hud_renderer, "ui_state", fake), \
         mock.patch.object(hud_renderer, "draw_accelerator_indicator",
                           lambda *a, **k: pulses.append(k["pulse"])), \
         mock.patch("pyray.get_time", lambda: 0.5):
      hud._draw_accelerator_state(rl.Rectangle(0, 0, 2160, 1080))
  assert pulses[:3] == [1.0, 1.0, 1.0]
  assert 0.0 <= pulses[3] < 1.0
