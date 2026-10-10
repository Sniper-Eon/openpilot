"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The accelerator's provisioning telemetry, where the mici models panel shows it:
big_model_progress() off jetlink's snapshot, ahead of the icon states, so
"building 42%" stands in for "getting ready" while an engine is built. The
fraction is only printed where a stage has one to measure: "waiting for the
accelerator" reads better than "connect 0%".
"""
import os
import unittest

os.environ["BIG"] = "0"
os.environ.setdefault("SCALE", "1")

from openpilot.common.prefix import OpenpilotPrefix
from openpilot.common.test import OpenpilotTestCase

# the window's own params, for whatever it reads while it comes up; every test
# then runs under its own prefix
_window_prefix = OpenpilotPrefix()


def setUpModule():
  """A hidden raylib window, once for the module: model_info reads ui_state,
  which builds widgets as it is imported."""
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  _window_prefix.__enter__()
  rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
  gui_app.init_window("test_big_model_progress", fps=30)


def tearDownModule():
  from openpilot.system.ui.lib.application import gui_app
  gui_app.close()
  _window_prefix.__exit__(None, None, None)


def snapshot(**fields):
  """jetlink's snapshot, nothing to show unless a field says so."""
  from jetlink.openpilot import Status
  values = {'enabled': False, 'mode': 'off', 'transport': 'USB', 'present': False, 'port': None, 'ready': False,
            'reason': None, 'progress': None, 'model': None, 'default_model': None}
  values.update(fields)
  return Status(**values)


class BigModelProgressTestCase(OpenpilotTestCase):
  def setUp(self):
    super().setUp()
    from openpilot.common.params import Params
    from openpilot.selfdrive.ui.ui_state import ui_state, ChestnutState
    self.ui_state = ui_state
    self.ChestnutState = ChestnutState
    ui_state.params = Params()
    ui_state.jetlink = None
    ui_state.chestnut_present = False
    ui_state.chestnut_active = None
    ui_state.chestnut_loading = False
    ui_state.chestnut_state = ChestnutState.DISCONNECTED

  def with_progress(self, progress):
    """The params pass's snapshot, read by model_info and the panel alike."""
    self.ui_state.jetlink = None if progress is None else snapshot(progress=progress)


class BigModelProgressTest(BigModelProgressTestCase):
  def test_no_snapshot_and_no_progress_are_no_progress(self):
    from openpilot.selfdrive.ui.sunnypilot.model_info import big_model_progress
    self.with_progress(None)
    assert big_model_progress() is None
    self.ui_state.jetlink = snapshot()
    assert big_model_progress() is None

  def test_a_finished_stage_is_no_progress(self):
    from openpilot.selfdrive.ui.sunnypilot.model_info import big_model_progress
    for progress in ({'stage': 'ready', 'frac': 1.0, 'msg': 'engine ready'}, {'stage': '', 'frac': 0.0, 'msg': ''}):
      self.with_progress(progress)
      assert big_model_progress() is None

  def test_a_working_stage_is_reported_whole(self):
    from openpilot.selfdrive.ui.sunnypilot.model_info import big_model_progress
    self.with_progress({'stage': 'build', 'frac': 0.4237, 'msg': 'building the model'})
    assert big_model_progress() == ('build', 0.4237, 'building the model')


class MiciModelsPanelTest(BigModelProgressTestCase):
  """The panel's info pair while the accelerator provisions."""

  def info(self):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts import models
    return models._model_info()

  def test_the_stage_and_fraction_are_shown(self):
    from openpilot.system.ui.lib.multilang import tr
    self.with_progress({'stage': 'build', 'frac': 0.4237, 'msg': 'building the model'})
    _, header, text = self.info()
    assert header == tr("big model")
    assert text == f"{tr('building the model')} 42%"

  def test_a_stage_with_nothing_to_measure_has_no_percentage(self):
    from openpilot.system.ui.lib.multilang import tr
    self.with_progress({'stage': 'connect', 'frac': 0.0, 'msg': 'waiting for the accelerator'})
    _, header, text = self.info()
    assert header == tr("big model")
    assert text == tr('waiting for the accelerator')

  def test_a_stage_with_no_message_names_the_stage(self):
    from openpilot.system.ui.lib.multilang import tr
    self.with_progress({'stage': 'download', 'frac': 0.5, 'msg': ''})
    assert self.info()[2] == f"{tr('download')} 50%"

  def test_a_failed_stage_is_unavailable(self):
    from openpilot.system.ui.lib.multilang import tr
    self.with_progress({'stage': 'failed', 'frac': 1.0, 'msg': 'could not download the large model'})
    _, header, text = self.info()
    assert header == tr("big model")
    assert text == tr("unavailable")

  def test_provisioning_wins_over_the_icon_state(self):
    from openpilot.system.ui.lib.multilang import tr
    # the panel's icon pair says "getting ready" for the same state; the
    # accelerator's own words are the more useful of the two
    self.ui_state.chestnut_state = self.ChestnutState.LOADING
    self.with_progress({'stage': 'download', 'frac': 0.1, 'msg': 'downloading the large model'})
    assert self.info()[2] == f"{tr('downloading the large model')} 10%"

    self.with_progress(None)
    assert self.info()[2] == tr("getting ready")


if __name__ == "__main__":
  unittest.main()
