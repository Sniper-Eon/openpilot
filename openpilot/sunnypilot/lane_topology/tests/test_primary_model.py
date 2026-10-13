from types import SimpleNamespace

import pytest

from openpilot.sunnypilot.lane_topology.adapter import LaneTopologyFrame
from openpilot.sunnypilot.lane_topology.primary_model import find_ego_source_ids, PrimaryLaneVisibilityFilter, \
                                                               PrimaryModelLaneTopologyAdapter, model_v2_to_observations
from openpilot.sunnypilot.lane_topology.types import LaneMarkingType


def model_fixture(probabilities=(0.9, 0.9, 0.9, 0.9)):
  lines = tuple(SimpleNamespace(x=(0.0, 5.0, 10.0, 40.0), y=(y, y, y, y), z=(0.0,) * 4)
                for y in (5.4, 1.8, -1.8, -5.4))
  return SimpleNamespace(laneLines=lines, laneLineProbs=probabilities)


def test_primary_model_reuses_four_visible_boundaries_without_gpu_imports():
  observations = model_v2_to_observations(model_fixture())
  assert len(observations) == 4
  assert [observation.source_id for observation in observations] == [0, 1, 2, 3]
  assert all(observation.marking_type == LaneMarkingType.unknown for observation in observations)
  assert [observation.points[0][1] for observation in observations] == [-5.4, -1.8, 1.8, 5.4]


def test_primary_model_filters_low_probability_outer_lines():
  observations = model_v2_to_observations(model_fixture((0.1, 0.8, 0.9, 0.2)))
  assert [observation.source_id for observation in observations] == [1, 2]


def test_marking_classifier_is_optional_and_explicit():
  observations = model_v2_to_observations(model_fixture(), marking_classifier=lambda index, line: LaneMarkingType.solid)
  assert all(observation.marking_type == LaneMarkingType.solid for observation in observations)


def test_adapter_accepts_model_v2_as_opaque_frame_payload():
  frame = LaneTopologyFrame(1, 2, model_fixture())
  observations = PrimaryModelLaneTopologyAdapter().infer(frame)
  assert len(observations) == 4


def test_visibility_hysteresis_retains_a_line_until_exit_threshold():
  visibility = PrimaryLaneVisibilityFilter(enter_threshold=0.5, exit_threshold=0.25)
  assert visibility.update((0.1, 0.6, 0.6, 0.1)) == frozenset((1, 2))
  assert visibility.update((0.1, 0.3, 0.4, 0.1)) == frozenset((1, 2))
  assert visibility.update((0.1, 0.2, 0.4, 0.1)) == frozenset((2,))


def test_default_visibility_keeps_confirmed_lines_down_to_twenty_percent():
  visibility = PrimaryLaneVisibilityFilter()
  assert visibility.update((0.9, 0.9, 0.9, 0.9)) == frozenset((0, 1, 2, 3))
  assert visibility.update((0.21, 0.21, 0.21, 0.21)) == frozenset((0, 1, 2, 3))
  assert visibility.update((0.19, 0.19, 0.19, 0.19)) == frozenset()


def test_primary_model_rejects_incomplete_contract():
  with pytest.raises(ValueError, match="exactly four"):
    model_v2_to_observations(SimpleNamespace(laneLines=(), laneLineProbs=()))


def test_find_ego_source_ids_ignores_outer_lines():
  observations = model_v2_to_observations(model_fixture())
  assert find_ego_source_ids(observations) == (2, 1)
