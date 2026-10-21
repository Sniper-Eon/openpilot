"""
Tesla factory lane-recognition signals for the C3.

Why this module exists
----------------------
This platform does not broadcast the raw per-line lane model
(``DAS_lanes`` / 0x239 with ``DAS_leftLineUsage`` / ``DAS_rightLineUsage``):
it is absent on every bus the panda sees. What the car *does* broadcast is the
verdict of its own lane recognition, which is what the lane-change gate needs:

============================  =======================================================
CAN message / signal          Meaning
============================  =======================================================
``0x39B DAS_status``
  ``DAS_autoLaneChangeState`` (46,5)   DAS lane-change verdict, including solid-line
                                       and lane-type blocks (see ``ALC_*`` below).
  ``DAS_laneDepartureWarning`` (37,3)  DAS line-crossing warning (left/right/severity).
``0x238 UI_driverAssistMapData``
  ``UI_rejectLeftLane`` (40)           Map/navigation rejects a left change.
  ``UI_rejectRightLane`` (41)          Map/navigation rejects a right change.
  ``UI_rejectLeftFreeSpace`` (44)      Map free-space rejects a left change.
  ``UI_rejectRightFreeSpace`` (45)     Map free-space rejects a right change.
  ``UI_navRouteActive`` (29)           Car navigation has an active route.
``0x399 DAS_statusCH``
  ``DAS_autoLaneChangeState`` (46,5)   Mirror copy, may lag behind 0x39B.
============================  =======================================================

All signals are little-endian (``@1+``) in the DBCs and are extracted with the
DBC start-bit numbering.

The class is dependency free (bytes in, flags out) so it can be unit tested on a
laptop without openpilot imports, and it keeps the last known state because the
CAN messages arrive at 2 Hz while the consumer runs at 20 Hz.
"""

from __future__ import annotations

import time

# ---------------------------------------------------------------------------
# DAS_autoLaneChangeState (0x39B / 0x399, start bit 46, 5 bits)
# ---------------------------------------------------------------------------
ALC_UNAVAILABLE_DISABLED = 0
ALC_UNAVAILABLE_NO_LANES = 1
ALC_UNAVAILABLE_SONICS_INVALID = 2
ALC_UNAVAILABLE_TP_FOLLOW = 3
ALC_UNAVAILABLE_EXITING_HIGHWAY = 4
ALC_UNAVAILABLE_VEHICLE_SPEED = 5
ALC_AVAILABLE_ONLY_L = 6
ALC_AVAILABLE_ONLY_R = 7
ALC_AVAILABLE_BOTH = 8
ALC_IN_PROGRESS_L = 9
ALC_IN_PROGRESS_R = 10
ALC_WAITING_SIDE_OBST_L = 11
ALC_WAITING_SIDE_OBST_R = 12
ALC_WAITING_FWD_OBST_L = 13
ALC_WAITING_FWD_OBST_R = 14
ALC_ABORT_SIDE_OBST_L = 15
ALC_ABORT_SIDE_OBST_R = 16
ALC_ABORT_POOR_VIEW = 17
ALC_ABORT_LC_HEALTH = 18
ALC_ABORT_BLINKER_OFF = 19
ALC_ABORT_OTHER = 20
ALC_UNAVAILABLE_SOLID_LANE_LINE = 21
ALC_BLOCKED_VEH_TTC_L = 22
ALC_BLOCKED_VEH_TTC_AND_USS_L = 23
ALC_BLOCKED_VEH_TTC_R = 24
ALC_BLOCKED_VEH_TTC_AND_USS_R = 25
ALC_BLOCKED_LANE_TYPE_L = 26
ALC_BLOCKED_LANE_TYPE_R = 27
ALC_WAITING_HANDS_ON = 28
ALC_ABORT_TIMEOUT = 29
ALC_ABORT_PLAN_INVALID = 30
ALC_SNA = 31

ALC_NAMES = {
  0: 'UNAVAILABLE_DISABLED',
  1: 'UNAVAILABLE_NO_LANES',
  2: 'UNAVAILABLE_SONICS_INVALID',
  3: 'UNAVAILABLE_TP_FOLLOW',
  4: 'UNAVAILABLE_EXITING_HIGHWAY',
  5: 'UNAVAILABLE_VEHICLE_SPEED',
  6: 'AVAILABLE_ONLY_L',
  7: 'AVAILABLE_ONLY_R',
  8: 'AVAILABLE_BOTH',
  9: 'IN_PROGRESS_L',
  10: 'IN_PROGRESS_R',
  11: 'WAITING_SIDE_OBST_L',
  12: 'WAITING_SIDE_OBST_R',
  13: 'WAITING_FWD_OBST_L',
  14: 'WAITING_FWD_OBST_R',
  15: 'ABORT_SIDE_OBST_L',
  16: 'ABORT_SIDE_OBST_R',
  17: 'ABORT_POOR_VIEW',
  18: 'ABORT_LC_HEALTH',
  19: 'ABORT_BLINKER_OFF',
  20: 'ABORT_OTHER',
  21: 'UNAVAILABLE_SOLID_LANE_LINE',
  22: 'BLOCKED_VEH_TTC_L',
  23: 'BLOCKED_VEH_TTC_AND_USS_L',
  24: 'BLOCKED_VEH_TTC_R',
  25: 'BLOCKED_VEH_TTC_AND_USS_R',
  26: 'BLOCKED_LANE_TYPE_L',
  27: 'BLOCKED_LANE_TYPE_R',
  28: 'WAITING_HANDS_ON',
  29: 'ABORT_TIMEOUT',
  30: 'ABORT_PLAN_INVALID',
  31: 'SNA',
}

# Verdicts that name a lane boundary the car itself refuses to cross.
# These are safe to veto unconditionally: they are the DAS lane-type result.
ALC_EXPLICIT_LEFT_BLOCK = frozenset((ALC_UNAVAILABLE_SOLID_LANE_LINE, ALC_BLOCKED_LANE_TYPE_L))
ALC_EXPLICIT_RIGHT_BLOCK = frozenset((ALC_UNAVAILABLE_SOLID_LANE_LINE, ALC_BLOCKED_LANE_TYPE_R))

# Verdicts that only say "auto lane change is not available on this side".
# They also depend on speed/map, so the caller should only veto with them when
# its own lane boundary evidence is inconclusive.
ALC_AVAIL_LEFT_BLOCK = frozenset((ALC_AVAILABLE_ONLY_R, ALC_IN_PROGRESS_R))
ALC_AVAIL_RIGHT_BLOCK = frozenset((ALC_AVAILABLE_ONLY_L, ALC_IN_PROGRESS_L))

# DAS_laneDepartureWarning (0x39B, start bit 37, 3 bits)
LDW_NONE = 0
LDW_LEFT_WARNING = 1
LDW_RIGHT_WARNING = 2
LDW_LEFT_WARNING_SEVERE = 3
LDW_RIGHT_WARNING_SEVERE = 4
LDW_SNA = 5

ADDRESS_DAS_STATUS = 0x39B
ADDRESS_DAS_STATUS_CH = 0x399
ADDRESS_UI_MAP_DATA = 0x238

# Both messages are about 2 Hz on the cars measured here. A veto that outlives
# its message is worse than no veto, so each signal expires on its own.
ALC_STALE_NS = 500_000_000
MAP_STALE_NS = 1_000_000_000
FRAME_BYTES = 8


def _le_bits(data: bytes, start: int, length: int) -> int:
  """Little-endian (Intel) DBC extraction."""
  return (int.from_bytes(data, 'little') >> start) & ((1 << length) - 1)


class OemLaneSignals:
  """Last known Tesla lane-recognition verdicts, fed from raw CAN frames."""

  def __init__(self) -> None:
    self.alc_state: int = -1          # DAS_autoLaneChangeState (0x39B)
    self.alc_state_ch: int = -1       # DAS_autoLaneChangeState (0x399 mirror)
    self.ldw: int = -1                # DAS_laneDepartureWarning
    self.reject_left_lane: bool = False
    self.reject_right_lane: bool = False
    self.reject_left_free_space: bool = False
    self.reject_right_free_space: bool = False
    self.nav_route_active: bool = False
    self.seen_alc: bool = False
    self.seen_map: bool = False
    self._alc_ns: int = -1
    self._alc_ch_ns: int = -1
    self._map_ns: int = -1

  # -- ingestion -----------------------------------------------------------
  def update(self, events, now_ns: int | None = None) -> None:
    """Consume messaging events (anything with a ``can`` frame list).

    ``now_ns`` exists for tests and replay; production uses the monotonic clock.
    Frames with an unexpected length are ignored, and every accepted frame
    refreshes the age of the signal it carried.
    """
    now = time.monotonic_ns() if now_ns is None else int(now_ns)
    for evt in events:
      for frame in evt.can:
        address = frame.address
        data = bytes(frame.dat)
        if len(data) != FRAME_BYTES:
          continue
        if address == ADDRESS_DAS_STATUS:
          self.alc_state = _le_bits(data, 46, 5)
          self.ldw = _le_bits(data, 37, 3)
          self._alc_ns = now
          self.seen_alc = True
        elif address == ADDRESS_DAS_STATUS_CH:
          self.alc_state_ch = _le_bits(data, 46, 5)
          self._alc_ch_ns = now
        elif address == ADDRESS_UI_MAP_DATA:
          self.reject_left_lane = bool(_le_bits(data, 40, 1))
          self.reject_right_lane = bool(_le_bits(data, 41, 1))
          self.reject_left_free_space = bool(_le_bits(data, 44, 1))
          self.reject_right_free_space = bool(_le_bits(data, 45, 1))
          self.nav_route_active = bool(_le_bits(data, 29, 1))
          self._map_ns = now
          self.seen_map = True

  @staticmethod
  def _fresh(stamp_ns: int, limit_ns: int, now_ns: int | None = None) -> bool:
    if stamp_ns < 0:
      return False
    now = time.monotonic_ns() if now_ns is None else int(now_ns)
    return 0 <= now - stamp_ns <= limit_ns

  @property
  def alc_fresh(self) -> bool:
    return self._fresh(self._alc_ns, ALC_STALE_NS)

  @property
  def map_fresh(self) -> bool:
    return self._fresh(self._map_ns, MAP_STALE_NS)

  # -- verdicts ------------------------------------------------------------
  @property
  def left_explicit_block(self) -> bool:
    """Car's own lane-type/solid-line (or map) verdict forbids a left change."""
    if self.alc_fresh and self.alc_state in ALC_EXPLICIT_LEFT_BLOCK:
      return True
    return bool(self.map_fresh and (self.reject_left_lane or self.reject_left_free_space))

  @property
  def right_explicit_block(self) -> bool:
    if self.alc_fresh and self.alc_state in ALC_EXPLICIT_RIGHT_BLOCK:
      return True
    return bool(self.map_fresh and (self.reject_right_lane or self.reject_right_free_space))

  @property
  def left_availability_block(self) -> bool:
    """Auto lane change is not available on the left (may be speed/map gated)."""
    return bool(self.alc_fresh and self.alc_state in ALC_AVAIL_LEFT_BLOCK)

  @property
  def right_availability_block(self) -> bool:
    return bool(self.alc_fresh and self.alc_state in ALC_AVAIL_RIGHT_BLOCK)

  @property
  def solid_line(self) -> bool:
    return bool(self.alc_fresh and self.alc_state == ALC_UNAVAILABLE_SOLID_LANE_LINE)

  def describe(self) -> str:
    alc = ALC_NAMES.get(self.alc_state, f'UNKNOWN({self.alc_state})')
    fresh = '' if self.alc_fresh else ' (stale)'
    return (f'alc={alc}{fresh} alc_ch={self.alc_state_ch} ldw={self.ldw} '
            f'map(L={self.reject_left_lane},R={self.reject_right_lane},'
            f'freeL={self.reject_left_free_space},freeR={self.reject_right_free_space},'
            f'nav={self.nav_route_active})')


# ---------------------------------------------------------------------------
# Self test: no openpilot dependencies, runs on any Python 3.10+
# ---------------------------------------------------------------------------
if __name__ == '__main__':
  class _Frame:
    def __init__(self, address: int, data: bytes):
      self.address = address
      self.dat = data

  class _Event:
    def __init__(self, frames):
      self.can = frames

  def frame(address: int, value: int, start: int, length: int) -> _Frame:
    raw = value << start
    data = bytes((raw >> (8 * i)) & 0xFF for i in range(8))
    return _Frame(address, data)

  cases = [
    ('solid lane line -> both explicit', [(0x39B, ALC_UNAVAILABLE_SOLID_LANE_LINE)], (True, True)),
    ('only right -> left avail', [(0x39B, ALC_AVAILABLE_ONLY_R)], (False, False)),
    ('blocked lane type L -> left explicit', [(0x39B, ALC_BLOCKED_LANE_TYPE_L)], (True, False)),
    ('both available -> nothing', [(0x39B, ALC_AVAILABLE_BOTH)], (False, False)),
  ]
  ok = True
  for name, frames, (want_left, want_right) in cases:
    sig = OemLaneSignals()
    sig.update([_Event([frame(0x39B, v, 46, 5) for _a, v in frames])])
    left_avail = want_left if name.startswith('solid') or name.startswith('blocked') else OemLaneSignals().left_availability_block
    got = (sig.left_explicit_block, sig.right_explicit_block)
    expect = (want_left, want_right)
    status = 'OK' if got == expect else 'FAIL'
    ok &= got == expect
    print(f'  {status}  {name}: got={got} want={expect}  ({sig.describe()})')

  # map reject bits
  sig = OemLaneSignals()
  raw = (1 << 41) | (1 << 29)
  sig.update([_Event([_Frame(0x238, bytes((raw >> (8 * i)) & 0xFF for i in range(8)))])])
  print(f'  {"OK" if sig.reject_right_lane and not sig.reject_left_lane and sig.nav_route_active else "FAIL"}'
        f'  0x238 right reject + nav: {sig.describe()}')
  # Staleness: an old verdict must stop vetoing once its message stops arriving.
  sig = OemLaneSignals()
  stale_ok = False
  sig.update([_Event([frame(0x39B, ALC_UNAVAILABLE_SOLID_LANE_LINE, 46, 5)])], now_ns=time.monotonic_ns() - 5_000_000_000)
  stale_ok = not sig.left_explicit_block and not sig.right_explicit_block
  print(f'  {"OK" if stale_ok else "FAIL"}  过期 solid 不再否决: {sig.describe()}')
  sig.update([_Event([frame(0x39B, ALC_UNAVAILABLE_SOLID_LANE_LINE, 46, 5)])])
  fresh_ok = sig.left_explicit_block and sig.right_explicit_block
  print(f'  {"OK" if fresh_ok else "FAIL"}  新 solid 仍然否决: {sig.describe()}')
  bad_frame = _Frame(0x39B, b'\x00')
  sig.update([_Event([bad_frame])])
  len_ok = sig.left_explicit_block  # short frame ignored, last fresh value kept
  print(f'  {"OK" if len_ok else "FAIL"}  短帧被忽略: {sig.describe()}')
  print('self test:', 'PASS' if (ok and stale_ok and fresh_ok and len_ok) else 'FAIL')
