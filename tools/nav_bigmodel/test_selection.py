"""Failures: enabling unrelated model, automatic actuation, lost saved pick,
disable/fault remaining enabled, importing heavy Mac code in the device owner.
"""
import unittest
from openpilot.sunnypilot.jetlink_adapter.nav_trial import override, shadow_only, ShadowGuard


class Selection(unittest.TestCase):
  def test_disabled_and_enabled(self):
    disabled = lambda: False
    enabled = lambda: True
    self.assertIsNone(override('ModelManager_ActiveBundleChestnut', disabled))
    self.assertEqual(override('ModelManager_ActiveBundleChestnut', enabled)['ref'],
                     'afbf2e547e9319e2eb9f515e1e4330af63705cec')
    self.assertIsNone(override('OtherSetting', enabled))
    self.assertTrue(shadow_only(enabled))
    self.assertFalse(shadow_only(disabled))

  def test_fault_disables(self):
    def broken(): raise RuntimeError('old Params ABI')
    self.assertIsNone(override('ModelManager_ActiveBundleChestnut', broken))
    self.assertFalse(shadow_only(broken))

  def test_disable_never_promotes_warmed_trial(self):
    from types import SimpleNamespace
    import threading
    active = [True]
    class Small:
      def run(self, *args): return 'small'
    class Joined:
      _joined = None
      _big = None
      _small_frames = 0
      _lock = threading.Lock()
      closed = False
      def run(self, *args): raise AssertionError('promotion path entered')
      def _adopt(self): pass
      def _run_small(self, *args): return 'small'
      def close(self): self.closed = True
    joined = Joined()
    guard = ShadowGuard(joined, Small(), lambda: active[0])
    self.assertEqual(guard.run({}, {}, {}), 'small')
    active[0] = False
    self.assertEqual(guard.run({}, {}, {}), 'small')
    guard._closer.join(timeout=1)
    self.assertTrue(joined.closed)

  def test_slow_link_close_does_not_block_small_model(self):
    import threading
    release = threading.Event()
    class Small:
      def run(self, *args): return 'small'
    class Joined:
      def close(self): release.wait(1)
    guard = ShadowGuard(Joined(), Small(), lambda: False)
    import time
    start = time.monotonic()
    try:
      self.assertEqual(guard.run({}, {}, {}), 'small')
      self.assertLess(time.monotonic() - start, 0.2)
    finally:
      release.set()


if __name__ == '__main__': unittest.main()
