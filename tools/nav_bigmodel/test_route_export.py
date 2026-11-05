"""Failures: stale/weak/disabled observations, mixed revisions/datums,
cross-machine clock confusion, future packets and delay renewing cached data."""
import unittest
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import Mock
from dataclasses import replace

from openpilot.sunnypilot.navassist.protocol import AcceptedSnapshot, parse_snapshot
from openpilot.sunnypilot.navassist.tests.test_protocol import payload, encode, SOURCE_WALL_MS
from openpilot.sunnypilot.navassist.route_geometry import Geometry
from openpilot.sunnypilot.navassist.trial_export import observation, TrialExporter
from tools.nav_bigmodel.pull_context import normalize


class RouteExport(unittest.TestCase):
  def setUp(self):
    self.current = AcceptedSnapshot(parse_snapshot(encode(payload())), 10_000_000_000, 10_500_000_000)
    self.geometry = Geometry('session-a', 1, 'a'*64, 'gcj02', ((31.2, 121.4), (31.21, 121.41)),
                             ((31.202, 121.395), (31.212, 121.405)), (0, 1), 2, 0., 1)

  def test_export_and_clock_conversion(self):
    data = observation(self.current, self.geometry, 10_100_000_000, SOURCE_WALL_MS+100, True)
    result = normalize(data, 10_200_000_000, 500_000_000_000, 500_100_000_000)
    self.assertEqual(result['captured_monotonic_ns'], 499_800_000_000)
    self.assertEqual(result['coordinate_system'], 'wgs84')
    self.assertEqual(result['route'][0], [121.395, 31.202])
    self.assertEqual(result['position']['age_ms'], 0)
    self.assertFalse(result['guidance']['valid'])
    with self.assertRaises(ValueError): normalize(data, 10_700_000_000, 500_000_000_000, 500_100_000_000)
    with self.assertRaises(ValueError): normalize(data, 10_000_000_000, 500_000_000_000, 500_100_000_000)
    with self.assertRaises(ValueError): normalize(data, 10_200_000_000, 500_000_000_000, 500_600_000_000)
    with self.assertRaises(ValueError): normalize(data, 10_400_000_000, 500_000_000_000, 500_200_000_000)

  def test_reject_unqualified_source(self):
    cases = [(self.current, self.geometry, 10_100_000_000, SOURCE_WALL_MS+100, False),
             (self.current, self.geometry, 10_600_000_000, SOURCE_WALL_MS+600, True),
             (self.current, replace(self.geometry, route_revision=2), 10_100_000_000, SOURCE_WALL_MS+100, True),
             (replace(self.current, snapshot=replace(self.current.snapshot, gps_weak=True)), self.geometry,
              10_100_000_000, SOURCE_WALL_MS+100, True),
             (self.current, self.geometry, 10_100_000_000, SOURCE_WALL_MS-100, True)]
    for args in cases:
      with self.subTest(args=args), self.assertRaises(ValueError): observation(*args)

  def test_private_atomic_export_disable_and_fault(self):
    now, wall = time.monotonic_ns(), time.time_ns()//1_000_000
    current = replace(self.current, receive_mono_ns=now, expires_mono_ns=now+500_000_000,
                      snapshot=replace(self.current.snapshot, source_wall_time_ms=wall, location_observed_at_ms=wall))
    store, cache, enabled = Mock(), Mock(), Mock(return_value=True)
    store.current.return_value, cache.current.return_value = current, self.geometry
    with tempfile.TemporaryDirectory() as folder:
      path = Path(folder)/'context.json'
      exporter = TrialExporter(store, cache, enabled, path)
      exporter.thread.start()
      try:
        deadline = time.monotonic()+.4
        while not path.exists() and time.monotonic() < deadline:
          time.sleep(.005)
        self.assertTrue(path.exists())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text())['sequence'], current.snapshot.sequence)
        enabled.return_value = False
        deadline = time.monotonic()+.3
        while path.exists() and time.monotonic() < deadline:
          time.sleep(.005)
        self.assertFalse(path.exists())
        enabled.side_effect = RuntimeError('parameter unavailable')
        time.sleep(.12)
        self.assertTrue(exporter.thread.is_alive())
        self.assertFalse(path.exists())
      finally:
        exporter.close()
      self.assertFalse(list(Path(folder).iterdir()))


if __name__ == '__main__': unittest.main()
