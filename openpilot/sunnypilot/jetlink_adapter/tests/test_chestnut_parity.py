"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

A chestnut on this branch behaves as it does on sunnypilot, except where
zoompilot does it better: the link stays off beside it, its failure is
upstream's own event and text, and a pick whose files are missing is kept
while the Default big model drives.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from jetlink.comma import gadget

from openpilot.common.params import Params
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.selfdrived.events import EVENTS, ET, EventName
from openpilot.sunnypilot import jetlink_adapter
from openpilot.sunnypilot.models import helpers
from openpilot.sunnypilot.models.fetcher import ModelParser

REF = 'b' * 40


class TestAlert(OpenpilotTestCase):
  def test_a_chestnut_is_told_to_restart_as_upstream_says(self):
    # only a chestnut raises it; an accelerator's loss is bigModelLinkLost,
    # a warning with the small model driving on (accelerator_events)
    alert = EVENTS[EventName.bigModelFailed][ET.PERMANENT]
    self.assertEqual(alert.alert_text_2, "Restart the car to retry,\nsmall model is still available")


class TestLinkStaysOff(OpenpilotTestCase):
  """Through the adapter, as manager, hardwared and the UI ask, with the link set
  to USB and a gadget that cannot come up."""

  def setUp(self):
    super().setUp()
    Params().put(jetlink_adapter.KEYS.link, jetlink_adapter.MODES.index('usb'), block=True)
    for p in (mock.patch.object(gadget, 'gadget_error', return_value='not set up'),
              mock.patch.object(jetlink_adapter, '_bound', None)):
      p.start()
      self.addCleanup(p.stop)

  def fitted(self, chestnut: bool):
    jetlink_adapter._bound = None   # a process of its own: the bus walk is cached
    return mock.patch('openpilot.selfdrive.modeld.helpers.chestnut_present', return_value=chestnut)

  def test_the_setting_on_beside_a_chestnut_is_off(self):
    with self.fitted(True):
      self.assertFalse(jetlink_adapter.should_run(False, None, None))
      status = jetlink_adapter.status()
      self.assertFalse(status.enabled or status.ready)
      self.assertIsNone(status.reason)
      self.assertIsNone(jetlink_adapter.reason())
      self.assertFalse(jetlink_adapter.prepare())

  def test_without_one_the_setting_decides(self):
    with self.fitted(False):
      self.assertTrue(jetlink_adapter.should_run(False, None, None))
      self.assertEqual(jetlink_adapter.reason(), 'not set up')
      self.assertEqual(jetlink_adapter.status().reason, 'not set up')

  def test_the_bus_walk_is_cached(self):
    with self.fitted(True) as probe:
      for _ in range(5):
        jetlink_adapter.should_run(False, None, None)
        jetlink_adapter.status()
    self.assertEqual(probe.call_count, 1)


class _Slots:
  """Params enough for the bundle validation: what it reads, writes and drops."""

  def __init__(self, values):
    self.values = dict(values)
    self.removed: list[str] = []

  def get(self, key, *a, **kw):
    return self.values.get(key)

  def put(self, key, value, block=False):
    self.values[key] = value

  def remove(self, key):
    self.removed.append(key)
    self.values.pop(key, None)


class TestPickKeptDefaultDrives(OpenpilotTestCase):
  """A chestnut pick whose files are not here runs as the Default big model."""

  def setUp(self):
    import tempfile
    self.root = tempfile.mkdtemp()
    bundle = ModelParser._parse_bundle({
      'index': 13, 'short_name': 'CTV3M', 'display_name': 'Cinque Terre V3', 'generation': '12',
      'environment': 'development', 'runner': 'tinygrad', 'is_20hz': True, 'ref': REF,
      'minimum_selector_version': str(helpers.REQUIRED_JSON_VERSION),
      'models': [{'type': 'supercombo', 'artifact': {'file_name': 'ctv3.pkl', 'download_uri': {'url': 'x', 'sha256': 's'}}}],
    })
    self.params = {helpers.ACTIVE_BUNDLE_KEYS['chestnut']: bundle.to_dict()}
    store = SimpleNamespace(get=lambda k, *a, **kw: self.params.get(k))
    for p in (mock.patch.object(helpers.Paths, 'model_root', return_value=self.root),):
      p.start()
      self.addCleanup(p.stop)
    self.store = store

  def active(self, chestnut=True):
    return helpers.get_active_bundle(self.store, chestnut=chestnut)  # type: ignore

  def test_missing_files_drive_the_default_and_keep_the_pick(self):
    self.assertIsNone(self.active())
    self.assertIn(helpers.ACTIVE_BUNDLE_KEYS['chestnut'], self.params)

  def test_validation_keeps_the_big_pick_it_cannot_look_for_yet(self):
    # the other half of the same contract: the pick is stored without its files on
    # purpose (the accelerator fetches its own representation, and a chestnut's
    # files are fetched by ModelManagerSP._fetch_big_model_files after this
    # validation runs). Resetting the big slot here would leave that fetch nothing
    # to do, so only the small slot's missing files are a reset
    raw = self.params[helpers.ACTIVE_BUNDLE_KEYS['chestnut']]
    listed = [helpers._parse_active_bundle(raw)]
    for source in ('chestnut', 'qcom'):
      key = helpers.ACTIVE_BUNDLE_KEYS[source]
      store = _Slots({key: raw})
      helpers._LAST_VALIDATED_RAW.clear()
      helpers._validate_active_bundle(store, source, listed)
      self.assertEqual(store.removed, [] if source == 'chestnut' else [key], source)

  def test_the_pick_drives_once_its_files_are_here(self):
    import os
    open(os.path.join(self.root, 'ctv3.pkl'), 'wb').close()
    self.assertEqual(self.active().ref, REF)

  def test_a_pick_being_fetched_again_drives_the_default(self):
    import os
    open(os.path.join(self.root, 'ctv3.pkl'), 'wb').close()
    self.params['ModelManager_DownloadRef'] = REF
    self.assertIsNone(self.active())

  def test_without_a_chestnut_the_small_slot_is_what_runs(self):
    # an empty small slot is not "nothing" on this branch when the big slot holds a
    # pick: jetlink stores the accelerator's own big model in
    # ModelManager_ActiveBundleChestnut (jetlink_adapter.KEYS.big_model) and the
    # branch runs the compiled default through modeld_v2 rather than handing modeld
    # a bundle whose files the accelerator fetches for itself. That bridge is
    # helpers.bundled_qcom_fallback, spec'd by
    # openpilot/sunnypilot/models/tests/test_bundled_fallback.py, and it is never
    # the big pick (models/tests/test_manager_download.py's TestActiveBundleSelection)
    self.params[helpers.ACTIVE_BUNDLE_KEYS['qcom']] = None
    with mock.patch.object(helpers, 'bundled_qcom_fallback', return_value='CD210 (Bundled)') as fallback:
      self.assertEqual(self.active(chestnut=False), 'CD210 (Bundled)')
    fallback.assert_called_once_with()
    self.params.clear()
    self.assertIsNone(self.active(chestnut=False), "no pick in either slot is the hardware default, which stock modeld runs")


if __name__ == '__main__':
  unittest.main()
