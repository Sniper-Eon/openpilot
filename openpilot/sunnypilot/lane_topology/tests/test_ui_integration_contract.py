from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_ui_integration_stays_out_of_model_planner_control_and_schema():
  ui_state = (ROOT / "openpilot/selfdrive/ui/sunnypilot/ui_state.py").read_text()
  hud = (ROOT / "openpilot/selfdrive/ui/mici/onroad/hud_renderer.py").read_text()
  road_view = (ROOT / "openpilot/selfdrive/ui/onroad/augmented_road_view.py").read_text()
  assert "LaneTopologyUIBridge" in ui_state
  assert "_draw_lane_topology" in hud
  assert "L:{type_text[left_type]}" in hud
  assert "visionbuf_luma" in road_view
  assert "PubMaster" not in ui_state
  assert "sendcan" not in ui_state
  # Jetlink keeps its existing read-only accelerator status subscription.
  assert 'self._accelerator_state_name = str(self.sm["modelDataV2SP"].acceleratorState)' in ui_state.replace(chr(39), chr(34))
  assert 'elif self.sm.seen["laneTopologyStateSP"]:' in ui_state


def test_tici_big_onroad_hud_renders_lane_and_navigation_overlay():
  hud = (ROOT / "openpilot/selfdrive/ui/sunnypilot/onroad/hud_renderer.py").read_text()
  assert "LaneNavigationOverlay" in hud
  assert "lane_navigation_overlay.render(rect)" in hud


def test_ui_accepts_current_bounded_navassist_pairing_record():
  ui_state = (ROOT / "openpilot/selfdrive/ui/sunnypilot/ui_state.py").read_text()
  assert 'apps = pairing.get("apps")' in ui_state
  assert 'self.nav_assist_track_mode = nav_assist_paired(' in ui_state
