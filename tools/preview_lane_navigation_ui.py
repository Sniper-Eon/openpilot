#!/usr/bin/env python3
"""Render the real tici overlay into a PNG without UI state or vehicle messages.

Example: python tools/preview_lane_navigation_ui.py --output /tmp/nav-ui.png
"""

import argparse
from pathlib import Path
from types import SimpleNamespace

import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.onroad.lane_navigation_overlay import LaneNavigationOverlay
from openpilot.selfdrive.ui.sunnypilot.onroad.lane_navigation_state import lane_display_from_service, navigation_display_from_service
from openpilot.system.ui.lib.application import FontWeight, gui_app


def preview_data(state: str):
  nav = SimpleNamespace(
    maneuver="turnRight", maneuverDistanceM=180.0, currentRoad="世纪大道", nextRoad="滨江东路",
    lanes=[], routeActive=True, routeMatched=True, stale=False, valid=True, rejectReason="none",
  )
  topology = SimpleNamespace(leftMarking="solid", rightMarking="dashed", egoLaneIndexFromLeft=1,
                             visibleLaneCount=3, valid=True, stale=False, ambiguous=False, validForControl=True)
  intent = SimpleNamespace(signalRequested=True, direction="right", targetLaneIndex=-1)
  if state == "stale":
    nav.stale = True
    nav.rejectReason = "stale"
    topology.stale = True
  elif state == "long-road":
    nav.currentRoad = "世纪大道高架快速路东延伸段"
    nav.nextRoad = "滨江东路临港工业园区连接线"
    topology.leftMarking = "doubleSolid"
  nav_display = navigation_display_from_service(
    nav, seen=True, alive=True, valid=True, lane_intent=intent, lane_intent_healthy=True,
    signal_configured=state != "disabled",
  )
  lane_display = lane_display_from_service(topology, seen=True, alive=True, valid=True)
  return lane_display, nav_display


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--output", type=Path, required=True)
  parser.add_argument("--width", type=int, default=2160)
  parser.add_argument("--height", type=int, default=1080)
  parser.add_argument("--state", choices=("active", "disabled", "stale", "long-road"), default="active")
  parser.add_argument("--background", type=Path)
  parser.add_argument("--bottom-inset", type=float, default=24.0)
  args = parser.parse_args()
  rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)
  rl.init_window(64, 64, "Navigation UI preview")
  gui_app._load_fonts()
  overlay = LaneNavigationOverlay()
  target = rl.load_render_texture(args.width, args.height)
  background = rl.load_texture(str(args.background)) if args.background else None
  rl.begin_texture_mode(target)
  rl.clear_background(rl.Color(27, 36, 46, 255))
  if background is not None:
    rl.draw_texture_pro(background, rl.Rectangle(0, 0, background.width, background.height),
                        rl.Rectangle(0, 0, args.width, args.height), rl.Vector2(0, 0), 0, rl.WHITE)
  else:
    # Schematic road context, not a captured drive or a claim of vehicle behavior.
    rl.draw_rectangle_gradient_v(0, 0, args.width, args.height, rl.Color(70, 94, 112, 255), rl.Color(32, 36, 42, 255))
    horizon = args.height * 0.38
    for side in (-1, 1):
      rl.draw_line_ex(rl.Vector2(args.width / 2 + side * 40, horizon),
                      rl.Vector2(args.width / 2 + side * args.width * 0.34, args.height), 7, rl.Color(175, 197, 202, 180))
    font = gui_app.font(FontWeight.BOLD)
    speed = "48"
    measured = rl.measure_text_ex(font, speed, 150, 0)  # noqa: TID251
    rl.draw_text_ex(font, speed, rl.Vector2((args.width - measured.x) / 2, 50), 150, 0, rl.WHITE)
    rl.draw_text_ex(font, "km/h", rl.Vector2(args.width / 2 - 39, 203), 31, 0, rl.Color(225, 234, 241, 255))
  lane, nav = preview_data(args.state)
  overlay.render_display(rl.Rectangle(0, 0, args.width, args.height), lane, nav, bottom_inset=args.bottom_inset)
  rl.end_texture_mode()
  image = rl.load_image_from_texture(target.texture)
  rl.image_flip_vertical(image)
  args.output.parent.mkdir(parents=True, exist_ok=True)
  if not rl.export_image(image, str(args.output)):
    raise RuntimeError(f"failed to export {args.output}")
  rl.unload_image(image)
  rl.unload_render_texture(target)
  if background is not None:
    rl.unload_texture(background)
  rl.close_window()
  print(args.output)


if __name__ == "__main__":
  main()
