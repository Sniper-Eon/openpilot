"""Which model is driving: the large accelerator model or the comma's own.

`ModelDataV2SP.acceleratorState` says what the joining model on the far end of
the Accelerator Link is doing (jetlink.openpilot.STATES: none, joining,
retrying, ready, running, unavailable), and every modeld publishes it on every
frame. Until now the UI only folded it into the chestnut icon's state, where
"the large model is driving" and "the large model is loaded and waiting for a
window to take over" are one green icon apart. On the road that is the whole
question: ready-but-never-taken means the link works and the handover does not.

So the indicator draws the state as words, in the top left under MAX, and only
where an accelerator is actually in play: no chestnut fitted (a board runs the
large model itself, upstream's icon says so) and either the link is on, a
far end is present, or the published state is one only an accelerator writes.
A drive with the link off and nothing published shows nothing.

The panel also names the model, so the two ends can be compared by eye: the
name here is the big slot's pick, or the accelerator's default while the link
is up and no pick is stored (jetlink's own default, CTV3M today).
"""
from __future__ import annotations

from dataclasses import dataclass

import pyray as rl

from openpilot.system.ui.lib.multilang import tr

# the levels, in the order the eye should rank them: a green pill means the
# large model is driving now, amber that it is ready but not driving, red that
# it cannot, dim that it is not up yet
RUNNING = "running"
READY = "ready"
JOINING = "joining"
RETRYING = "retrying"
UNAVAILABLE = "unavailable"
INITIALIZING = "initializing"

# acceleratorState values that only an accelerator publishes: a device with
# jetlink absent or the link off never sees them, so they count as "something
# is there" even when the params snapshot says nothing (a link turned on after
# the last params pass, or a params library too old for the setting)
_ACCELERATOR_STATES = frozenset({"joining", "ready", "running", "retrying"})

# the fallback label when no name can be found anywhere; the accelerator's own
# default, named here only so the row is never empty
DEFAULT_ACCELERATOR_MODEL = "CTV3M"


@dataclass(frozen=True)
class AcceleratorStatus:
  """One row of the onroad indicator, already worded and levelled."""
  visible: bool
  level: str
  headline: str
  detail: str
  model: str = ""


@dataclass(frozen=True)
class AcceleratorIndicatorStyle:
  font_size: int
  line_height: int
  padding: int
  min_width: int
  offset_x: int
  offset_y: int


def accelerator_indicator_style() -> AcceleratorIndicatorStyle:
  # under the MAX box (y=45..249) and under a speed-limit sign beside it
  # (which reaches y=261): the comma 3X's header has room for one more row
  # there and nothing else draws in it
  return AcceleratorIndicatorStyle(font_size=44, line_height=56, padding=20, min_width=420,
                                   offset_x=60, offset_y=310)


def bundle_model_name(bundle) -> str:
  """The display name of a model bundle from either place it is read: the
  params pass hands over a dict, the model manager a ModelBundle. Empty when
  there is nothing to name."""
  if bundle is None:
    return ""
  if isinstance(bundle, dict):
    name = bundle.get("displayName") or bundle.get("internalName")
  else:
    name = getattr(bundle, "displayName", "") or getattr(bundle, "internalName", "")
  return str(name) if name else ""


def should_show_accelerator_indicator(*, started: bool, chestnut_present: bool, link_mode: str,
                                      jetlink_enabled: bool, jetlink_present: bool,
                                      state: str) -> bool:
  """Whether an accelerator is in play at all: the gate for the whole pill.

  A fitted chestnut runs the large model itself and owns the upstream icon, and
  offroad there is nothing driving to report. Otherwise a link that is on, a
  far end on the cable, or a state only an accelerator writes earns the row.
  """
  if not started or chestnut_present:
    return False
  return bool(link_mode != "off" or jetlink_enabled or jetlink_present or state in _ACCELERATOR_STATES)


def build_accelerator_status(*, state: str, model_name: str = "", jetlink_view=None,
                             visible: bool = True) -> AcceleratorStatus:
  """The indicator's contents for one frame: `state` is the acceleratorState
  name, `model_name` the big slot's pick, and `jetlink_view` an optional
  jetlink snapshot for the link's own default name. Pure: the caller resolves
  the inputs, so the wording and the levels are tested without a device."""
  if not visible:
    return AcceleratorStatus(False, "", "", "")

  name = (model_name or "").strip()
  if not name and jetlink_view is not None:
    name = str(getattr(jetlink_view, "model", "") or getattr(jetlink_view, "default_model", "") or "").strip()
  if not name:
    name = DEFAULT_ACCELERATOR_MODEL

  if state == "running":
    return AcceleratorStatus(True, RUNNING, tr("Large model is driving"),
                             tr("Handed over: the accelerator runs this model now"), name)
  if state == "ready":
    return AcceleratorStatus(True, READY, tr("Large model is ready"),
                             tr("Loaded, waiting for a takeover window"), name)
  if state == "joining":
    return AcceleratorStatus(True, JOINING, tr("Large model is joining"),
                             tr("Link is up, the accelerator has not taken over"), name)
  if state == "retrying":
    return AcceleratorStatus(True, RETRYING, tr("Large model is retrying"),
                             tr("Join failed, the accelerator is trying again"), name)
  if state == "unavailable":
    return AcceleratorStatus(True, UNAVAILABLE, tr("Large model unavailable"),
                             tr("The accelerator reported the link cannot run"), name)
  if state in ("none", ""):
    return AcceleratorStatus(True, INITIALIZING, tr("Small model is driving"),
                             tr("No accelerator state published yet"), name)
  # a state this build does not know: show it as it arrived rather than hide it
  return AcceleratorStatus(True, UNAVAILABLE, tr("Large model unavailable"), state, name)


def accelerator_status() -> AcceleratorStatus:
  """The status for this frame, read off ui_state.

  A chestnut and an offroad screen are quiet; so is a link that is off with no
  record of a far end. The acceleratorState is read from the same place the
  params pass reads it, and the big slot's pick from the params pass's own
  `active_bundle` (the manager's JSON is not re-parsed per frame)."""
  from openpilot.selfdrive.ui.sunnypilot.accelerator_link import link_mode
  from openpilot.selfdrive.ui.ui_state import ui_state

  view = ui_state.jetlink_view
  state = ui_state._accelerator_state_name
  visible = should_show_accelerator_indicator(
    started=ui_state.started, chestnut_present=ui_state.chestnut_present, link_mode=link_mode(),
    jetlink_enabled=bool(view is not None and view.enabled),
    jetlink_present=bool(view is not None and view.present), state=state)
  return build_accelerator_status(state=state, model_name=bundle_model_name(ui_state.active_bundle),
                                  jetlink_view=view, visible=visible)


# level -> (headline, detail, border, opaque fill) while the pill is solid
_LEVEL_COLORS = {
  RUNNING: (rl.Color(80, 240, 130, 255), rl.Color(210, 255, 225, 255),
            rl.Color(80, 240, 130, 255), rl.Color(16, 68, 34, 230)),
  READY: (rl.Color(255, 190, 70, 255), rl.Color(255, 240, 210, 255),
          rl.Color(255, 190, 70, 255), rl.Color(58, 42, 10, 220)),
  JOINING: (rl.Color(255, 190, 70, 255), rl.Color(255, 240, 210, 255),
            rl.Color(255, 190, 70, 190), rl.Color(40, 30, 10, 190)),
  RETRYING: (rl.Color(255, 130, 110, 255), rl.Color(255, 225, 220, 255),
             rl.Color(255, 130, 110, 255), rl.Color(62, 20, 16, 220)),
  UNAVAILABLE: (rl.Color(210, 210, 210, 255), rl.Color(230, 230, 230, 255),
                rl.Color(200, 200, 200, 190), rl.Color(24, 24, 24, 190)),
  INITIALIZING: (rl.Color(220, 220, 220, 255), rl.Color(225, 225, 225, 255),
                 rl.Color(200, 200, 200, 170), rl.Color(24, 24, 24, 180)),
}


def indicator_colors(level: str, pulse: float = 1.0) -> tuple[rl.Color, rl.Color, rl.Color, rl.Color]:
  """(headline, detail, border, fill) for a level, faded by `pulse` 0..1. The
  joining level never solidifies: a steady amber "ready" and a breathing amber
  "joining" are two different verdicts on a drive."""
  headline, detail, border, fill = _LEVEL_COLORS.get(level, _LEVEL_COLORS[UNAVAILABLE])
  alpha = max(0.35, min(1.0, pulse))
  return (rl.Color(headline.r, headline.g, headline.b, int(headline.a * alpha)),
          rl.Color(detail.r, detail.g, detail.b, int(detail.a * alpha)),
          rl.Color(border.r, border.g, border.b, int(border.a * alpha)),
          rl.Color(fill.r, fill.g, fill.b, int(fill.a * max(0.85, alpha))))


def draw_accelerator_indicator(rect: rl.Rectangle, font: rl.Font, font_bold: rl.Font, *, pulse: float = 1.0) -> None:
  """The pill itself, top left under the MAX box. `pulse` is 0..1, driven by
  the caller so the joining level can breathe."""
  from openpilot.system.ui.lib.text_measure import measure_text_cached

  status = accelerator_status()
  if not status.visible:
    return

  style = accelerator_indicator_style()
  width = max(style.min_width, int(measure_text_cached(font_bold, status.headline, style.font_size).x) + style.padding * 2)
  height = style.line_height * 2 + style.padding
  pill = rl.Rectangle(rect.x + style.offset_x, rect.y + style.offset_y, width, height)
  headline_color, detail_color, border_color, fill_color = indicator_colors(status.level, pulse)

  rl.draw_rectangle_rounded(pill, 0.25, 12, fill_color)
  border = 4 if status.level in (RUNNING, READY, RETRYING) else 2
  rl.draw_rectangle_rounded_lines_ex(pill, 0.25, 12, border, border_color)

  text_x = pill.x + style.padding
  rl.draw_text_ex(font_bold, status.headline, rl.Vector2(text_x, pill.y + style.padding * 0.4),
                  style.font_size, 0, headline_color)
  detail = f"{status.model} · {status.detail}" if status.model else status.detail
  rl.draw_text_ex(font, detail, rl.Vector2(text_x, pill.y + style.padding * 0.4 + style.line_height),
                  style.font_size, 0, detail_color)
