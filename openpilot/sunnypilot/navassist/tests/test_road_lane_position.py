import json
from types import SimpleNamespace

import pytest

from openpilot.sunnypilot.navassist.position_feedback import lane_position_feedback
from openpilot.sunnypilot.navassist.road_lane_position import (
  MAX_RECORD_BYTES,
  build_position_record,
  clear_position_record,
  record_is_fresh,
  unknown_position_record,
  write_position_record,
)

NOW_NS = 5_000_000_000


def snapshot(session_id: str = 'nav-session', route_revision: int = 3) -> SimpleNamespace:
  return SimpleNamespace(session_id=session_id, route_revision=route_revision)


def confirmed_record(**overrides) -> dict:
  values = dict(lane_index=2, lane_count=4, absolute_confirmed=True, nav_session_id='nav-session',
                route_revision=3, stable_samples=3, capture_mono_ns=NOW_NS - 100_000_000)
  values.update(overrides)
  return build_position_record(**values)


def test_a_confirmed_record_is_accepted_with_its_real_age(tmp_path):
  path = tmp_path / 'position.json'
  write_position_record(confirmed_record(), path=path, now_ns=NOW_NS)

  value = lane_position_feedback(snapshot(), path=path, now_ns=NOW_NS)

  assert value['valid'] is True
  assert value['laneIndex'] == 2 and value['laneCount'] == 4
  assert value['ageMs'] == 100
  assert value['numbering'] == 'leftToRight' and value['source'] == 'commaCamera'


def test_less_than_three_stable_samples_cannot_be_confirmed(tmp_path):
  path = tmp_path / 'position.json'
  record = confirmed_record(stable_samples=2)

  assert record['valid'] is False and record['absolute_confirmed'] is False
  assert record['lane_index'] is None and record['lane_count'] is None
  write_position_record(record, path=path, now_ns=NOW_NS)
  assert lane_position_feedback(snapshot(), path=path, now_ns=NOW_NS)['valid'] is False


def test_an_unconfirmed_record_always_clears_the_index():
  for overrides in (dict(absolute_confirmed=False, lane_index=2, lane_count=4),
                    dict(absolute_confirmed=True, stable_samples=0, lane_index=2),
                    dict(absolute_confirmed=False, lane_index=2, lane_count=None)):
    record = confirmed_record(**overrides)
    assert record['valid'] is False and record['lane_index'] is None and record['lane_count'] is None, overrides


def test_bad_input_is_refused_instead_of_being_written():
  for overrides in (dict(absolute_confirmed=True, lane_index=0),
                    dict(absolute_confirmed=True, lane_index=13),
                    dict(absolute_confirmed=True, lane_index=3, lane_count=2),
                    dict(absolute_confirmed=True, lane_count=True),
                    dict(absolute_confirmed=True, lane_index=True),
                    dict(absolute_confirmed=True, nav_session_id=None),
                    dict(absolute_confirmed='yes'),
                    dict(route_revision=-1),
                    dict(capture_mono_ns=0),
                    dict(capture_mono_ns=1.5),
                    dict(stable_samples=-1)):
    with pytest.raises(ValueError):
      confirmed_record(**overrides)


def test_a_confirmed_record_may_omit_the_total_but_not_the_index(tmp_path):
  path = tmp_path / 'position.json'
  record = confirmed_record(lane_count=None)
  write_position_record(record, path=path, now_ns=NOW_NS)

  value = lane_position_feedback(snapshot(), path=path, now_ns=NOW_NS)

  assert value['valid'] is True and value['laneIndex'] == 2 and value['laneCount'] is None


def test_the_reader_rejects_another_session_route_or_an_expired_capture(tmp_path):
  path = tmp_path / 'position.json'

  write_position_record(confirmed_record(), path=path, now_ns=NOW_NS)
  for changed in (snapshot(session_id='other'), snapshot(route_revision=9)):
    assert lane_position_feedback(changed, path=path, now_ns=NOW_NS)['valid'] is False

  expired = confirmed_record(capture_mono_ns=NOW_NS - 3_000_000_000)
  assert record_is_fresh(expired, now_ns=NOW_NS) is False
  # The writer refuses to publish an already-expired confirmation.
  with pytest.raises(ValueError):
    write_position_record(expired, path=path, now_ns=NOW_NS)
  # And the reader independently rejects it if it appears anyway.
  path.write_text(json.dumps(expired))
  assert lane_position_feedback(snapshot(), path=path, now_ns=NOW_NS)['valid'] is False


def test_an_explicit_unknown_or_a_removed_file_reads_as_unknown(tmp_path):
  path = tmp_path / 'position.json'
  record = unknown_position_record(nav_session_id='nav-session', route_revision=3, capture_mono_ns=NOW_NS)

  assert record['valid'] is False and record['absolute_confirmed'] is False
  write_position_record(record, path=path, now_ns=NOW_NS)
  assert lane_position_feedback(snapshot(), path=path, now_ns=NOW_NS)['valid'] is False

  clear_position_record(path=path)
  assert not path.exists()
  assert lane_position_feedback(snapshot(), path=path, now_ns=NOW_NS)['valid'] is False


def test_a_record_stays_within_the_reader_size_limit():
  record = confirmed_record()
  assert len(json.dumps(record).encode()) < MAX_RECORD_BYTES
