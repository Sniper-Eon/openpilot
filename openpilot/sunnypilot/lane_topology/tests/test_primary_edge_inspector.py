from io import StringIO
import json
import pytest

from openpilot.cereal import log
from tools.inspect_primary_lane_edges import inspect_events


def test_real_cereal_geometry_survives_export_with_device_sign_and_time():
  event = log.Event.new_message()
  event.valid, event.logMonoTime = True, 200
  model = event.init('modelV2')
  model.frameId, model.timestampEof = 42, 190
  for field, values in (('laneLines', (-5.4, -1.8, 1.8, 5.4)), ('roadEdges', (-5.4, 5.4))):
    for curve, y in zip(model.init(field, len(values)), values, strict=True):
      curve.x = [0., 10., 30.]
      curve.y = [y] * 3
  model.laneLineProbs = [.9] * 4
  model.roadEdgeStds = [.1] * 2
  output = StringIO()
  summary = inspect_events([event.as_reader()], output)
  record = json.loads(output.getvalue())
  assert record['model']['roadEdges'][0]['y'][0] == pytest.approx(-5.4)
  assert record['capture_mono_ns'] == 190
  assert record['candidate']['candidate_index'] == 2
  assert record['candidate']['candidate_count'] == 3
  assert record['candidate']['absolute_confirmed'] is False
  assert summary['candidate_pairs'] == {'2/3': 1}
  assert summary['absolute_confirmations'] == 0
  assert summary['accuracy'] is None


def test_empty_input_does_not_claim_a_tested_lane():
  summary = inspect_events([], StringIO())
  assert summary['model_frames'] == 0
  assert summary['candidate_pairs'] == {}
  assert summary['accuracy'] is None


def test_real_nan_geometry_is_preserved_as_null_and_not_a_lane_claim():
  event = log.Event.new_message()
  model = event.init('modelV2')
  for field, count in (('laneLines', 4), ('roadEdges', 2)):
    for curve in model.init(field, count):
      curve.x = [0., 30.]
      curve.y = [float('nan'), float('nan')]
  model.laneLineProbs = [.9] * 4
  model.roadEdgeStds = [.1] * 2
  output = StringIO()
  inspect_events([event.as_reader()], output)
  record = json.loads(output.getvalue())
  assert record['model']['roadEdges'][0]['y'] == [None, None]
  assert record['candidate']['candidate_index'] is None
  assert record['candidate']['reason'] == 'malformedGeometry'
