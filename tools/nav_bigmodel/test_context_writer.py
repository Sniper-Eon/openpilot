"""Failures: stale source, mixed coordinates, bad fix, refreshed old timestamp,
invalid distance or command, and half-written context reaching inference."""
import time
import unittest
from unittest.mock import patch
import numpy as np
from tools.nav_bigmodel.render_context import render


class Writer(unittest.TestCase):
  def packet(self):
    return {'active': True, 'coordinate_system': 'wgs84', 'captured_monotonic_ns': 9_600_000_000,
            'route': [[113, 23], [113.001, 23.001]],
            'position': {'longitude': 113, 'latitude': 23, 'speed_mps': 0, 'has_fix': True, 'age_ms': 1700},
            'guidance': {'valid': True, 'age_ms': 1700, 'command': 8, 'distance_m': 50}}

  @patch('tools.nav_bigmodel.render_context.time.monotonic', return_value=10)
  def test_transit_delay_expires_position(self, _clock):
    with self.assertRaises(ValueError): render(self.packet(), None)

  @patch('tools.nav_bigmodel.render_context.time.monotonic', return_value=10)
  def test_transit_delay_expires_guidance(self, _clock):
    packet = self.packet()
    packet['position']['age_ms'] = 100
    renderer = unittest.mock.Mock()
    renderer.render.return_value = (np.zeros((256, 256), np.uint8), True)
    _, nav, _, _ = render(packet, renderer)
    self.assertFalse(nav.any())

  def test_reject_unqualified_inputs_before_render(self):
    for packet in ({}, {'active': True, 'coordinate_system': 'gcj02'},
                   {'active': True, 'coordinate_system': 'wgs84', 'captured_monotonic_ns': 0}):
      with self.assertRaises(ValueError): render(packet, None)


if __name__ == '__main__': unittest.main()
