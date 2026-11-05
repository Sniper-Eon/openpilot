"""Failures: stale source, mixed coordinates, bad fix, refreshed old timestamp,
invalid distance or command, and half-written context reaching inference."""
import time
import unittest
from tools.nav_bigmodel.render_context import render


class Writer(unittest.TestCase):
  def test_reject_unqualified_inputs_before_render(self):
    for packet in ({}, {'active': True, 'coordinate_system': 'gcj02'},
                   {'active': True, 'coordinate_system': 'wgs84', 'captured_monotonic_ns': 0}):
      with self.assertRaises(ValueError): render(packet, None)


if __name__ == '__main__': unittest.main()
