"""Producer side of the display-only absolute lane position contract.

:mod:`openpilot.sunnypilot.navassist.position_feedback` is the authority for the
file's field names and acceptance rules. This module only builds and writes a
record that reader can accept, and it never upgrades an unconfirmed claim: when
the caller has no absolute confirmation the record carries ``valid=false`` and
``absolute_confirmed=false`` with a null index.

The caller must stamp ``nav_session_id`` with the **currently accepted navigation
session** and ``route_revision`` with that session's route, because the reader
rejects evidence from another session or route. ``capture_mono_ns`` stays the
vision capture time, so the reader's monotonic age keeps growing instead of
being reset by the write.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

from openpilot.sunnypilot.navassist.settings import atomic_json

POSITION_PATH = Path('/dev/shm/road_lane_position.json')
VERSION = 1
NUMBERING = 'leftToRight'
SOURCE = 'commaCamera'
MAX_LANE_INDEX = 12
MIN_STABLE_SAMPLES = 3
MAX_AGE_MS = 2_000
MAX_RECORD_BYTES = 4_096


def _finite_int(value: object, *, name: str, low: int, high: int) -> int:
  # bool is an int subclass; an explicit `True` must not pass as 1.
  if type(value) is not int or not low <= value <= high:
    raise ValueError(f'{name} must be an integer within [{low}, {high}]')
  return value


def build_position_record(*, lane_index: object = None, lane_count: object = None,
                          absolute_confirmed: object = False, nav_session_id: object = None,
                          route_revision: object = 0, stable_samples: object = 0,
                          capture_mono_ns: object = 0) -> dict:
  """Return the exact record the C3 reader validates, or raise on bad input."""

  if type(absolute_confirmed) is not bool:
    raise ValueError('absolute_confirmed must be a boolean')
  revision = _finite_int(route_revision, name='route_revision', low=0, high=2**63 - 1)
  captured = _finite_int(capture_mono_ns, name='capture_mono_ns', low=1, high=2**63 - 1)
  stable = _finite_int(stable_samples, name='stable_samples', low=0, high=2**31 - 1)

  confirmed = absolute_confirmed and stable >= MIN_STABLE_SAMPLES
  if not confirmed:
    # An unconfirmed claim must clear the index; retaining a remembered lane is
    # exactly the failure mode the reader exists to prevent.
    return {
      'version': VERSION, 'valid': False, 'absolute_confirmed': False,
      'numbering': NUMBERING, 'nav_session_id': nav_session_id if isinstance(nav_session_id, str) else None,
      'route_revision': revision, 'stable_samples': stable, 'capture_mono_ns': captured,
      'lane_index': None, 'lane_count': None,
    }

  if not isinstance(nav_session_id, str) or not nav_session_id:
    raise ValueError('a confirmed record needs the accepted navigation session id')
  index = _finite_int(lane_index, name='lane_index', low=1, high=MAX_LANE_INDEX)
  if lane_count is None:
    count: int | None = None
  else:
    count = _finite_int(lane_count, name='lane_count', low=index, high=MAX_LANE_INDEX)
  return {
    'version': VERSION, 'valid': True, 'absolute_confirmed': True,
    'numbering': NUMBERING, 'nav_session_id': nav_session_id,
    'route_revision': revision, 'stable_samples': stable, 'capture_mono_ns': captured,
    'lane_index': index, 'lane_count': count,
  }


def record_is_fresh(record: dict, *, now_ns: int | None = None) -> bool:
  now = time.monotonic_ns() if now_ns is None else now_ns
  captured = record.get('capture_mono_ns')
  return type(captured) is int and 0 <= now - captured < MAX_AGE_MS * 1_000_000


def write_position_record(record: dict, *, path: Path = POSITION_PATH, now_ns: int | None = None) -> None:
  """Atomically publish a validated record, refusing an already-expired claim."""
  if record.get('absolute_confirmed') and not record_is_fresh(record, now_ns=now_ns):
    # Publishing a stale confirmation would let the phone show an old lane until
    # the reader's own deadline passes; make the caller clear it instead.
    raise ValueError('refusing to publish an expired absolute confirmation')
  encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
  if len(encoded.encode()) > MAX_RECORD_BYTES:
    raise ValueError('position record exceeds the reader size limit')
  atomic_json(path, record)


def clear_position_record(*, path: Path = POSITION_PATH) -> None:
  """Remove the record so every reader immediately reports unknown."""
  path.unlink(missing_ok=True)


def unknown_position_record(*, nav_session_id: str | None = None, route_revision: int = 0,
                            capture_mono_ns: int | None = None) -> dict:
  """Explicit unknown for a session change, occlusion, timeout or shutdown."""
  return build_position_record(
    absolute_confirmed=False, nav_session_id=nav_session_id, route_revision=route_revision,
    stable_samples=0,
    capture_mono_ns=time.monotonic_ns() if capture_mono_ns is None else capture_mono_ns,
  )


def publish_decision(decision, *, nav_session_id: str | None, route_revision: int,
                     path: Path = POSITION_PATH, now_ns: int | None = None) -> dict:
  """Publish one absolute lane gate decision, returning the record actually written.

  ``decision`` is duck-typed on ``valid``, ``lane_index``, ``lane_count``,
  ``stable_samples`` and ``capture_mono_ns``, which is the shape of
  ``lane_topology.absolute_lane.AbsoluteLaneDecision``. Keeping it duck-typed
  means this writer never has to import the vision stack.

  An unconfirmed decision must overwrite the file with an explicit unknown rather
  than simply not writing. Leaving the previous confirmation in place would keep
  the phone showing a lane number the evidence no longer supports until the
  reader's own deadline happened to expire it.

  A confirmation that is already older than the reader's lifetime is downgraded
  to unknown instead of being published stale or raising into a live loop.
  """
  if not decision.valid:
    record = build_position_record(
      absolute_confirmed=False, nav_session_id=nav_session_id, route_revision=route_revision,
      stable_samples=decision.stable_samples,
      capture_mono_ns=decision.capture_mono_ns or _monotonic_ns(now_ns),
    )
    write_position_record(record, path=path, now_ns=now_ns)
    return record

  record = build_position_record(
    lane_index=decision.lane_index, lane_count=decision.lane_count, absolute_confirmed=True,
    nav_session_id=nav_session_id, route_revision=route_revision,
    stable_samples=decision.stable_samples, capture_mono_ns=decision.capture_mono_ns,
  )
  try:
    write_position_record(record, path=path, now_ns=now_ns)
  except ValueError:
    record = build_position_record(
      absolute_confirmed=False, nav_session_id=nav_session_id, route_revision=route_revision,
      stable_samples=decision.stable_samples, capture_mono_ns=_monotonic_ns(now_ns),
    )
    write_position_record(record, path=path, now_ns=now_ns)
  return record


def _monotonic_ns(now_ns: int | None) -> int:
  return time.monotonic_ns() if now_ns is None else now_ns
