from __future__ import annotations

from importlib.resources import as_file
import math

import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.onroad.lane_navigation_state import (
  LaneOverlayDisplay,
  NavigationOverlayDisplay,
  lane_display_from_service,
  lane_display_from_ui_bridge,
  navigation_display_from_service,
  overlay_layout,
)
from openpilot.system.ui.lib.application import FONT_DIR, FontWeight, gui_app


BACKGROUND = rl.Color(9, 15, 23, 226)
TEXT = rl.Color(248, 251, 255, 255)
SECONDARY = rl.Color(183, 197, 211, 255)
ACCENT = rl.Color(90, 210, 255, 255)
WARNING = rl.Color(255, 200, 97, 255)


class LaneNavigationOverlay:
  """Read-only onroad presentation; render_display also serves the local preview."""

  def __init__(self):
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._text_font: rl.Font | None = None
    self._characters: set[str] = set()
    self._measurements: dict[tuple[str, int, bool], rl.Vector2] = {}

  def render(self, rect: rl.Rectangle) -> None:
    from openpilot.selfdrive.ui.ui_state import ui_state

    sm = ui_state.sm
    nav_seen = sm.seen["navAssistStateSP"]
    lane_display = lane_display_from_service(
      sm["laneTopologyStateSP"], seen=sm.seen["laneTopologyStateSP"],
      alive=sm.alive["laneTopologyStateSP"], valid=sm.valid["laneTopologyStateSP"],
    )
    if lane_display is None:
      lane_display = lane_display_from_ui_bridge(ui_state.lane_topology, ui_state.lane_topology_bridge.ego_marking_types())
    nav_display = navigation_display_from_service(
      sm["navAssistStateSP"], seen=nav_seen, alive=sm.alive["navAssistStateSP"], valid=sm.valid["navAssistStateSP"],
      lane_intent=sm["navLaneIntentSP"],
      lane_intent_healthy=sm.seen["navLaneIntentSP"] and sm.alive["navLaneIntentSP"] and sm.valid["navLaneIntentSP"],
      decel_active=(sm.alive["longitudinalPlanSP"] and sm.valid["longitudinalPlanSP"] and
                    str(sm["longitudinalPlanSP"].longitudinalPlanSource) == "navAssist"),
      signal_configured=ui_state.tesla_turn_signal_configured,
    )
    # Seeing UDP navigation is sufficient. Legacy pairing only supplies an
    # initial placeholder before this process has observed its first message.
    if nav_seen or ui_state.nav_assist_track_mode:
      if lane_display is None:
        lane_display = LaneOverlayDisplay("左侧  未知", "车道识别中", "右侧  未知")
      if nav_display is None:
        nav_display = NavigationOverlayDisplay("等待手机导航", "在 TesNav 中开始导航", "同一局域网自动连接")

    bottom_inset = 84.0 if int(ui_state.developer_ui or 0) in (1, 3) else 24.0
    self.render_display(rect, lane_display, nav_display, bottom_inset=bottom_inset)

  def render_display(self, rect: rl.Rectangle, lane_display: LaneOverlayDisplay | None,
                     nav_display: NavigationOverlayDisplay | None, *, bottom_inset: float = 24.0) -> None:
    if lane_display is None and nav_display is None:
      return
    texts = []
    if nav_display is not None:
      texts.extend((nav_display.title, nav_display.subtitle, nav_display.detail, nav_display.instruction))
    if lane_display is not None:
      texts.extend((lane_display.left, lane_display.center, lane_display.right))
    self._prepare_text(texts)
    layout = overlay_layout(rect.width, rect.height, bottom_inset=bottom_inset)
    if nav_display is not None:
      self._draw_navigation(self._offset(layout.navigation, rect), nav_display, lane_display)
    elif lane_display is not None:
      self._draw_lane_strip(self._offset(layout.navigation, rect), lane_display)

  def _prepare_text(self, texts: list[str]) -> None:
    # Road names are dynamic and not necessarily in the UI translation atlas.
    # Cache the required CJK glyphs; changing distances never reloads a font.
    required = set("".join(texts)) | set(map(chr, range(32, 127))) | {"…"}
    required.difference_update({"\n", "\r", "\t"})
    if self._text_font is not None and required <= self._characters:
      return
    characters = self._characters | required
    if len(characters) > 1024:
      characters = required
    points = sorted(map(ord, characters))
    point_buffer = rl.ffi.new("int[]", points)
    with as_file(FONT_DIR.joinpath("NotoSansCJKsc-Navigation.otf")) as font_path:
      font = rl.load_font_ex(str(font_path), 48, rl.ffi.cast("int *", point_buffer), len(points))
    rl.set_texture_filter(font.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    if self._text_font is not None:
      rl.unload_font(self._text_font)
    self._text_font = font
    self._characters = characters
    self._measurements.clear()

  @staticmethod
  def _offset(values: tuple[float, float, float, float], rect: rl.Rectangle) -> rl.Rectangle:
    x, y, width, height = values
    return rl.Rectangle(rect.x + x, rect.y + y, width, height)

  @staticmethod
  def _card(box: rl.Rectangle) -> None:
    rl.draw_rectangle_rounded(box, 0.18, 10, BACKGROUND)
    rl.draw_rectangle_rounded_lines_ex(box, 0.18, 10, 1.2, rl.Color(122, 148, 173, 125))

  def _draw_navigation(self, box: rl.Rectangle, display: NavigationOverlayDisplay,
                       lane_display: LaneOverlayDisplay | None) -> None:
    self._card(box)
    accent = WARNING if display.warning else ACCENT if display.linked else SECONDARY
    rl.begin_scissor_mode(int(box.x), int(box.y), int(box.width), int(box.height))
    compact = box.width < 700
    footer_height = 44.0 if lane_display is not None else 0.0
    content_height = box.height - footer_height
    rl.draw_rectangle_rounded(
      rl.Rectangle(box.x + 5, box.y + 14, 5, max(10, content_height - 28)), 0.8, 6, accent,
    )
    icon_size = 64.0 if compact else 76.0
    icon_box = rl.Rectangle(box.x + 22, box.y + (content_height - icon_size) / 2, icon_size, icon_size)
    self._draw_maneuver(icon_box, display.maneuver if display.current_guidance else "none", accent)
    x = icon_box.x + icon_box.width + 20
    available = max(0, box.x + box.width - 20 - x)
    if display.current_guidance:
      size = 45 if compact else 54
      distance = self._fit(display.distance, available, size, bold=True)
      self._draw_text(distance, x, box.y + 9, size, TEXT, bold=True)
      instruction_x = x + self._measure(distance, size, True).x + 22
      instruction_size = 34 if compact else 40
      instruction = self._fit(display.instruction, box.x + box.width - 20 - instruction_x, instruction_size)
      self._draw_text(instruction, instruction_x, box.y + 17, instruction_size, TEXT)
    else:
      self._draw_text(self._fit(display.title, available, 36), x, box.y + 17, 36, TEXT)
    self._draw_text(self._fit(display.subtitle, available, 25), x, box.y + 65, 25, SECONDARY)
    self._draw_text(self._fit(display.detail, available, 24), x, box.y + 95, 24, accent)
    if lane_display is not None:
      self._draw_lane_footer(rl.Rectangle(box.x, box.y + box.height - footer_height, box.width, footer_height), lane_display)
    rl.end_scissor_mode()

  def _draw_lane_strip(self, box: rl.Rectangle, display: LaneOverlayDisplay) -> None:
    strip = rl.Rectangle(box.x, box.y + box.height - 52, box.width, 52)
    self._card(strip)
    self._draw_lane_footer(strip, display)

  def _draw_lane_footer(self, box: rl.Rectangle, display: LaneOverlayDisplay) -> None:
    rl.draw_line_ex(rl.Vector2(box.x + 18, box.y), rl.Vector2(box.x + box.width - 18, box.y),
                    1.0, rl.Color(89, 111, 135, 150))
    left_box = rl.Rectangle(box.x + 18, box.y, box.width * 0.36 - 18, box.height)
    center_box = rl.Rectangle(box.x + box.width * 0.36, box.y, box.width * 0.28, box.height)
    right_box = rl.Rectangle(box.x + box.width * 0.64, box.y, box.width * 0.36 - 18, box.height)
    self._draw_inline_marking(left_box, display.left, display.left_marking, display.reliable, align_right=False)
    self._draw_centered(center_box, self._fit(display.center, center_box.width - 12, 22), 22, SECONDARY)
    self._draw_inline_marking(right_box, display.right, display.right_marking, display.reliable, align_right=True)

  def _draw_inline_marking(self, box: rl.Rectangle, text: str, marking: str, reliable: bool, *, align_right: bool) -> None:
    color = self._marking_color(marking, reliable)
    label = self._fit(text.replace("  ", " "), box.width - 42, 23)
    label_width = self._measure(label, 23).x
    x = box.x + box.width - label_width if align_right else box.x + 34
    self._draw_text(label, x, box.y + (box.height - self._measure(label, 23).y) / 2, 23, color)
    marker_x = x - 18 if align_right else box.x + 10
    dashed = marking in ("dashed", "doubleDashed")
    double = marking in ("doubleSolid", "doubleDashed", "solidDashed")
    if marking == "unknown" or not reliable:
      for y in (box.y + 14, box.y + 22, box.y + 30):
        rl.draw_circle(int(marker_x), int(y), 1.8, color)
      return
    for stroke in range(2 if double else 1):
      sx = marker_x + stroke * 6
      if dashed or (marking == "solidDashed" and stroke == 1):
        for y in (box.y + 10, box.y + 23):
          rl.draw_line_ex(rl.Vector2(sx, y), rl.Vector2(sx, y + 8), 3, color)
      else:
        rl.draw_line_ex(rl.Vector2(sx, box.y + 10), rl.Vector2(sx, box.y + 34), 3, color)

  @staticmethod
  def _draw_maneuver(box: rl.Rectangle, maneuver: str, color: rl.Color) -> None:
    if maneuver in ("none", "unknown"):
      for x in (0.41, 0.59):
        rl.draw_line_ex(rl.Vector2(box.x + box.width * x, box.y + box.height * 0.30),
                        rl.Vector2(box.x + box.width * x, box.y + box.height * 0.70), 6, color)
      return
    if maneuver == "destination":
      rl.draw_circle_lines(int(box.x + box.width / 2), int(box.y + box.height / 2), box.width * 0.22, color)
      rl.draw_circle(int(box.x + box.width / 2), int(box.y + box.height / 2), box.width * 0.09, color)
      return
    right = "Right" in maneuver
    if maneuver.startswith("uTurn"):
      points = [(0.72, 0.79), (0.72, 0.32), (0.60, 0.23), (0.40, 0.23), (0.28, 0.32), (0.28, 0.67)]
    elif maneuver in ("turnLeft", "turnRight"):
      points = [(0.70, 0.80), (0.70, 0.40), (0.26, 0.40)]
    elif maneuver in ("sharpLeft", "sharpRight"):
      points = [(0.72, 0.82), (0.72, 0.30), (0.35, 0.30), (0.23, 0.54)]
    elif maneuver == "roundabout":
      points = [(0.50, 0.89)] + [
        (0.50 + 0.27 * math.cos(math.pi / 2 + step * math.pi * 1.7 / 18),
         0.50 + 0.27 * math.sin(math.pi / 2 + step * math.pi * 1.7 / 18)) for step in range(19)
      ]
    elif maneuver == "straight":
      points = [(0.50, 0.80), (0.50, 0.22)]
    else:
      points = [(0.68, 0.80), (0.68, 0.57), (0.25, 0.23)]
    if right:
      points = [(1.0 - x, y) for x, y in points]
    vertices = [rl.Vector2(box.x + box.width * x, box.y + box.height * y) for x, y in points]
    for start, end in zip(vertices[:-1], vertices[1:], strict=True):
      rl.draw_line_ex(start, end, box.width * 0.08, color)
    end, previous = vertices[-1], vertices[-2]
    angle = math.atan2(end.y - previous.y, end.x - previous.x)
    for offset in (-0.70, 0.70):
      tail = rl.Vector2(end.x - box.width * 0.22 * math.cos(angle + offset),
                        end.y - box.width * 0.22 * math.sin(angle + offset))
      rl.draw_line_ex(end, tail, box.width * 0.08, color)

  def _draw_lane(self, box: rl.Rectangle, text: str, marking: str, reliable: bool) -> None:
    self._card(box)
    color = self._marking_color(marking, reliable)
    compact = box.width < 240
    start_x = box.x + (18 if compact else 26)
    dashed = marking in ("dashed", "doubleDashed")
    double = marking in ("doubleSolid", "doubleDashed", "solidDashed")
    if marking == "unknown" or not reliable:
      for y in (19, 31, 43):
        rl.draw_circle(int(start_x), int(box.y + y), 2.5, color)
    else:
      for stroke in range(2 if double else 1):
        x = start_x + stroke * 10
        if dashed or (marking == "solidDashed" and stroke == 1):
          for y in (15, 29, 43):
            rl.draw_line_ex(rl.Vector2(x, box.y + y), rl.Vector2(x, box.y + y + 7), 4, color)
        else:
          rl.draw_line_ex(rl.Vector2(x, box.y + 14), rl.Vector2(x, box.y + 49), 4, color)
    x = box.x + (44 if compact else 66)
    size = 25 if compact else 30
    label = self._fit(text.replace("  ", " "), box.x + box.width - x - 12, size)
    self._draw_text(label, x, box.y + (box.height - self._measure(label, size).y) / 2, size, color)

  @staticmethod
  def _marking_color(marking: str, reliable: bool) -> rl.Color:
    if not reliable or marking == "unknown":
      return SECONDARY
    return WARNING if marking in ("solid", "doubleSolid", "solidDashed", "roadEdge") else rl.Color(131, 231, 198, 255)

  def _measure(self, text: str, size: int, bold: bool = False) -> rl.Vector2:
    key = (text, size, bold)
    if key not in self._measurements:
      if len(self._measurements) >= 1024:
        self._measurements.clear()
      self._measurements[key] = rl.measure_text_ex(self._font_bold if bold else self._text_font, text, size, 0)  # noqa: TID251
    return self._measurements[key]

  def _draw_text(self, text: str, x: float, y: float, size: int, color: rl.Color, *, bold: bool = False) -> None:
    # These locally loaded road-name glyphs must not be replaced by the global
    # translation-only fallback atlas. Measurement and drawing use the same font.
    draw = getattr(rl, "_orig_draw_text_ex", rl.draw_text_ex)
    draw(self._font_bold if bold else self._text_font, text, rl.Vector2(x, y), size, 0, color)

  def _draw_centered(self, box: rl.Rectangle, text: str, size: int, color: rl.Color) -> None:
    measured = self._measure(text, size)
    self._draw_text(text, box.x + (box.width - measured.x) / 2, box.y + (box.height - measured.y) / 2, size, color)

  def _fit(self, text: str, max_width: float, size: int, bold: bool = False) -> str:
    if max_width <= 0:
      return ""
    if self._measure(text, size, bold).x <= max_width:
      return text
    start, end = 0, len(text)
    while start < end:
      middle = (start + end + 1) // 2
      if self._measure(text[:middle] + "…", size, bold).x <= max_width:
        start = middle
      else:
        end = middle - 1
    return text[:start] + "…" if self._measure("…", size, bold).x <= max_width else ""
