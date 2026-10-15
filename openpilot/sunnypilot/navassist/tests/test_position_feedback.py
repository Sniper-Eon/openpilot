import json
from types import SimpleNamespace
import pytest
from openpilot.sunnypilot.navassist.position_feedback import lane_position_feedback


def test_only_fresh_absolute_session_bound_evidence_can_be_numbered(tmp_path):
  snapshot = SimpleNamespace(session_id='test', route_revision=2)
  path = tmp_path/'position.json'
  d = dict(version=1, valid=True, absolute_confirmed=True, numbering='leftToRight',
           nav_session_id='test', route_revision=2, stable_samples=3,
           capture_mono_ns=1_000_000_000, lane_index=2, lane_count=4)
  path.write_text(json.dumps(d))
  value = lane_position_feedback(snapshot, path=path, now_ns=1_200_000_000)
  assert value['valid'] and value['laneIndex'] == 2 and value['laneCount'] == 4
  assert value['ageMs'] == 200
  for change in ({'absolute_confirmed': False}, {'valid': False}, {'nav_session_id': 'old'},
                 {'route_revision': 1}, {'stable_samples': 2}, {'lane_index': 0}, {'lane_index': 5},
                 {'lane_count': True}, {'lane_index': True}, {'version': True},
                 {'capture_mono_ns': -2_000_000_000}, {'capture_mono_ns': 2_000_000_000}):
    path.write_text(json.dumps(d | change))
    out = lane_position_feedback(snapshot, path=path, now_ns=1_200_000_000)
    assert out['valid'] is False and out['laneIndex'] is None, change
  path.unlink()
  assert not lane_position_feedback(snapshot, path=path)['valid']


def test_visible_corridor_cannot_be_used_as_road_index(tmp_path):
  path=tmp_path/'position.json'
  path.write_text(json.dumps(dict(valid=True,absolute_confirmed=False,visible_lane_count=1,ego_lane_index=0)))
  value=lane_position_feedback(SimpleNamespace(session_id='test',route_revision=2),path=path)
  assert not value['valid'] and value['laneIndex'] is None
