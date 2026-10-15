import ast
import json
from pathlib import Path

import pytest

from openpilot.sunnypilot.lane_topology.absolute_lane import AbsoluteLaneGate
from openpilot.sunnypilot.lane_topology.types import LaneMarkingType, LaneTopologyState
from tools.evaluate_absolute_lane_labels import evaluate_absolute_labels
from tools.replay_absolute_lane import (
  FRAMES_SCHEMA,
  LANE_ANCHOR,
  REPORT_SCHEMA,
  boundary_from_json,
  parse_marking_type,
  parse_topology_state,
  replay_frames,
)

ROOT = Path(__file__).resolve().parents[4]


def frame(frame_id: int, capture_ns: int, *, ego_y_m: float = 0.0, state: str = 'normal',
          session_id: str | None = None, route_revision: int | None = None,
          boundaries: list[dict] | None = None, left_edge: int = 10, right_edge: int = 13) -> dict:
  record = {
    'frame_id': frame_id, 'capture_mono_ns': capture_ns, 'ego_y_m': ego_y_m, 'topology_state': state,
    'left_edge_track_id': left_edge, 'right_edge_track_id': right_edge,
    'boundaries': boundaries if boundaries is not None else three_lane_boundaries(),
  }
  if session_id is not None:
    record['session_id'] = session_id
  if route_revision is not None:
    record['route_revision'] = route_revision
  return record


def three_lane_boundaries() -> list[dict]:
  return [
    {'track_id': 10, 'marking_type': 'roadEdge', 'confidence': 0.9, 'points': [[0.0, 5.25], [30.0, 5.25]]},
    {'track_id': 11, 'marking_type': 'dashed', 'confidence': 0.9, 'points': [[0.0, 1.75], [30.0, 1.75]]},
    {'track_id': 12, 'marking_type': 'dashed', 'confidence': 0.9, 'points': [[0.0, -1.75], [30.0, -1.75]]},
    {'track_id': 13, 'marking_type': 'roadEdge', 'confidence': 0.9, 'points': [[0.0, -5.25], [30.0, -5.25]]},
  ]


def document(frames: list[dict]) -> dict:
  return {'schema': FRAMES_SCHEMA, 'segment': 'drive-01', 'session_id': 'replay-session',
          'route_revision': 1, 'frames': frames}


def test_the_replay_tool_is_offline_and_touches_no_vehicle_interface():
  source = (ROOT / 'tools/replay_absolute_lane.py').read_text()
  ast.parse(source)
  for forbidden in ('PubMaster', 'SubMaster', 'Params', 'sendcan', 'messaging', 'VisionIpcClient',
                    'modelV2', 'carControl', 'openpilot.selfdrive'):
    assert forbidden not in source, forbidden
  for required in ('AbsoluteLaneGate', 'evaluate_absolute_labels', FRAMES_SCHEMA, REPORT_SCHEMA):
    assert required in source, required


def test_a_three_lane_carriageway_is_only_confirmed_after_three_consistent_frames():
  report = replay_frames(document([frame(index, 1_000_000_000 + index * 100_000_000) for index in range(3)]))

  assert report['schema'] == REPORT_SCHEMA and report['segment'] == 'drive-01'
  reasons = [record['reason'] for record in report['records']]
  assert reasons == ['stabilizing', 'stabilizing', 'absoluteConfirmed']
  confirmed = report['records'][-1]
  assert confirmed['valid'] is True and confirmed['lane_index'] == 2 and confirmed['lane_count'] == 3
  assert [record['stable_samples'] for record in report['records']] == [1, 2, 3]


def test_an_untyped_outer_boundary_keeps_every_frame_unknown():
  boundaries = three_lane_boundaries()
  boundaries[0]['marking_type'] = 'unknown'
  report = replay_frames(document([frame(index, 1_000_000_000 + index * 100_000_000, boundaries=boundaries)
                                   for index in range(4)]))

  assert all(record['valid'] is False for record in report['records'])
  assert report['records'][-1]['reason'] == 'edgeMarkingNotConfirmed'
  assert report['records'][-1]['lane_index'] is None


def test_a_merge_and_a_session_change_both_clear_a_confirmed_index():
  frames = [frame(index, 1_000_000_000 + index * 100_000_000) for index in range(3)]
  frames.append(frame(3, 1_300_000_000, state='mergingLeft'))
  frames.append(frame(4, 1_400_000_000, session_id='other-session'))
  frames.append(frame(5, 1_500_000_000, session_id='other-session'))
  report = replay_frames(document(frames))

  records = report['records']
  assert records[2]['valid'] is True
  assert (records[3]['valid'], records[3]['reason']) == (False, 'topology:mergingLeft')
  assert records[4]['valid'] is False and records[4]['stable_samples'] == 1
  assert records[5]['valid'] is False and records[5]['stable_samples'] == 2


def test_the_report_scores_against_human_labels_with_false_positives_kept_separate():
  frames = [frame(index, 1_000_000_000 + index * 100_000_000, ego_y_m=0.0) for index in range(3)]
  frames.append(frame(3, 1_300_000_000, ego_y_m=3.5))
  frames.append(frame(4, 1_400_000_000, ego_y_m=3.5))
  frames.append(frame(5, 1_500_000_000, ego_y_m=3.5))
  report = replay_frames(document(frames))
  labels = {'schema': 'lane-position-ground-truth-v1', 'segment': 'drive-01', 'labels': [
    {'frame_index': index, 'lane_index': 2, 'lane_count': 3} for index in range(3)
  ] + [{'frame_index': 3, 'lane_index': 1, 'lane_count': 3},
       {'frame_index': 4, 'lane_index': 1, 'lane_count': 3},
       {'frame_index': 5, 'lane_index': 1, 'lane_count': 3}]}

  metrics = evaluate_absolute_labels(report, labels)

  # Only the third frame of each ego position is stable enough to answer.
  assert metrics['labeled'] == 6 and metrics['known'] == 2 and metrics['correct'] == 2
  assert metrics['false_positives'] == 0
  assert metrics['coverage'] == pytest.approx(2 / 6)
  assert metrics['unknown_reasons'] == {'stabilizing': 4}


def test_a_wrong_confirmed_index_is_counted_as_a_false_positive():
  report = replay_frames(document([frame(index, 1_000_000_000 + index * 100_000_000) for index in range(3)]))
  labels = {'schema': 'lane-position-ground-truth-v1', 'segment': 'drive-01',
            'labels': [{'frame_index': 2, 'lane_index': 3, 'lane_count': 3}]}

  metrics = evaluate_absolute_labels(report, labels)

  assert metrics['known'] == 1 and metrics['correct'] == 0
  assert metrics['false_positives'] == 1 and metrics['false_positive_rate'] == 1.0
  assert metrics['false_positive_pairs'] == {'3': {'2': 1}}


def test_the_replay_rejects_malformed_input_instead_of_guessing():
  with pytest.raises(ValueError):
    replay_frames({'schema': 'other', 'segment': 'x', 'frames': [frame(0, 1)]})
  with pytest.raises(ValueError):
    replay_frames(document([]))
  with pytest.raises(ValueError):
    replay_frames(document([frame(0, 1) | {'capture_mono_ns': 0}]))
  with pytest.raises(ValueError):
    replay_frames(document([frame(0, 1) | {'topology_state': 'invented'}]))
  with pytest.raises(ValueError):
    replay_frames(document([frame(0, 1, boundaries=[three_lane_boundaries()[0],
                                                    three_lane_boundaries()[0]])]))
  with pytest.raises(ValueError):
    boundary_from_json({'track_id': 1, 'points': [[0.0, float('nan')], [1.0, 1.0]]})
  with pytest.raises(ValueError):
    boundary_from_json({'track_id': 1, 'points': [[0.0, 1.0]]})
  with pytest.raises(ValueError):
    parse_marking_type('yellowDouble')
  with pytest.raises(ValueError):
    parse_topology_state('forking')


def test_the_parser_accepts_every_declared_marking_and_topology_name():
  for name in LaneMarkingType.__members__:
    assert parse_marking_type(name) is LaneMarkingType[name]
  assert parse_topology_state(None) is LaneTopologyState.normal
  for name in LaneTopologyState.__members__:
    assert parse_topology_state(name) is LaneTopologyState[name]
  parsed = boundary_from_json({'track_id': 3, 'points': [[0, 2], [10, 2]], 'confidence': 0.5})
  assert parsed.track_id == 3 and parsed.marking_type is LaneMarkingType.unknown and parsed.confidence == 0.5


def test_a_caller_supplied_gate_continues_its_stability_window():
  frames = document([frame(index, 1_000_000_000 + index * 100_000_000) for index in range(2)])
  gate = AbsoluteLaneGate()
  first = replay_frames(frames, gate=gate)

  # Reusing a gate carries the evidence window into the later frames.
  later = document([frame(index, 1_200_000_000 + index * 100_000_000) for index in range(2)])
  second = replay_frames(later, gate=gate)

  # A fresh gate starts over.
  fresh = replay_frames(frames)

  assert first['records'][-1]['stable_samples'] == 2 and first['records'][-1]['valid'] is False
  assert second['records'][-1]['stable_samples'] == 4 and second['records'][-1]['valid'] is True
  assert fresh['records'][-1]['stable_samples'] == 2 and fresh['records'][-1]['valid'] is False
  assert json.loads(json.dumps(fresh)) == fresh


# --- anchored mode ---------------------------------------------------------

ANCHOR = 5


def anchored_boundaries() -> list[dict]:
  """Four lanes, the outermost lane marking at -7.0 and a 2.1 m shoulder beyond."""
  return [
    {'track_id': 1, 'marking_type': 'doubleSolid', 'confidence': 0.9, 'points': [[0.0, 7.0], [30.0, 7.0]]},
    {'track_id': 2, 'marking_type': 'dashed', 'confidence': 0.9, 'points': [[0.0, 3.5], [30.0, 3.5]]},
    {'track_id': 3, 'marking_type': 'dashed', 'confidence': 0.9, 'points': [[0.0, 0.0], [30.0, 0.0]]},
    {'track_id': 4, 'marking_type': 'dashed', 'confidence': 0.9, 'points': [[0.0, -3.5], [30.0, -3.5]]},
    {'track_id': ANCHOR, 'marking_type': 'solid', 'confidence': 0.9, 'points': [[0.0, -7.0], [30.0, -7.0]]},
    {'track_id': 6, 'marking_type': 'roadEdge', 'confidence': 0.9, 'points': [[0.0, -9.1], [30.0, -9.1]]},
  ]


def anchored_frame(frame_id: int, capture_ns: int, *, anchor: int = ANCHOR, ego_y_m: float = 1.75,
                   lane_total: int | None = None, boundaries: list[dict] | None = None) -> dict:
  record = {'frame_id': frame_id, 'capture_mono_ns': capture_ns, 'ego_y_m': ego_y_m,
            'right_anchor_track_id': anchor,
            'boundaries': boundaries if boundaries is not None else anchored_boundaries()}
  if lane_total is not None:
    record['lane_total'] = lane_total
  return record


def anchored_document(frames: list[dict], *, lane_total: int | None = 4) -> dict:
  document = {'schema': FRAMES_SCHEMA, 'segment': 'drive-01', 'session_id': 'replay-session',
              'route_revision': 1, 'gate': LANE_ANCHOR, 'frames': frames}
  if lane_total is not None:
    document['lane_total'] = lane_total
  return document


def test_the_anchored_gate_numbers_from_the_outermost_lane_marking():
  report = replay_frames(anchored_document(
    [anchored_frame(index, 1_000_000_000 + index * 100_000_000) for index in range(3)]))

  assert report['gate'] == LANE_ANCHOR
  assert [record['reason'] for record in report['records']] == ['stabilizing', 'stabilizing',
                                                               'absoluteConfirmed']
  confirmed = report['records'][-1]
  assert confirmed['valid'] is True and confirmed['lane_index'] == 2 and confirmed['lane_count'] == 4


def test_the_map_total_comes_from_the_document_unless_the_frame_overrides_it():
  frames = [anchored_frame(index, 1_000_000_000 + index * 100_000_000) for index in range(3)]
  # Three lines lie between this ego position and the anchor, so a three lane
  # road cannot also contain it; the frame's own total overrides the document's.
  frames[2] = {**frames[2], 'ego_y_m': 5.25, 'lane_total': 3}
  assert replay_frames(anchored_document(frames))['records'][-1]['reason'] == 'mapTotalInconsistent'

  # With the document total of four the same position is consistent, and the
  # changed index restarts the window instead of being reported.
  frames[2] = {**frames[2], 'lane_total': 4}
  assert replay_frames(anchored_document(frames))['records'][-1]['reason'] == 'stabilizing'


def test_an_absent_total_or_anchor_is_refused_and_reported():
  without_total = anchored_document(
    [anchored_frame(0, 1_000_000_000)], lane_total=None)
  without_anchor = anchored_document([anchored_frame(0, 1_000_000_000, anchor=-1)])

  assert replay_frames(without_total)['records'][-1]['reason'] == 'laneTotalUnavailable'
  assert replay_frames(without_anchor)['records'][-1]['reason'] == 'laneAnchorNotObserved'


def test_an_unsupported_gate_or_a_fractional_total_is_refused():
  document = anchored_document([anchored_frame(0, 1_000_000_000)])

  with pytest.raises(ValueError):
    replay_frames({**document, 'gate': 'invented'})
  with pytest.raises(ValueError):
    replay_frames({**document, 'lane_total': 4.0})
  with pytest.raises(ValueError):
    replay_frames(anchored_document([anchored_frame(0, 1_000_000_000, lane_total=4.0)]))


def test_an_anchored_report_still_scores_against_human_labels():
  report = replay_frames(anchored_document(
    [anchored_frame(index, 1_000_000_000 + index * 100_000_000) for index in range(3)]))
  labels = {'schema': 'lane-position-ground-truth-v1', 'segment': 'drive-01',
            'labels': [{'frame_index': 2, 'lane_index': 2, 'lane_count': 4}]}

  metrics = evaluate_absolute_labels(report, labels)

  assert metrics['known'] == 1 and metrics['correct'] == 1 and metrics['false_positives'] == 0
