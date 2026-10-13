from types import SimpleNamespace

import numpy as np

from openpilot.sunnypilot.lane_topology.ui_bridge import LaneTopologyUIBridge, visionbuf_luma
from openpilot.sunnypilot.lane_topology.types import LaneMarkingType


def model_fixture(frame_id: int, probabilities=(0.9, 0.9, 0.9, 0.9)):
  # Real modelV2 uses right-positive y and orders lines from image-left to image-right.
  lines = tuple(SimpleNamespace(x=(0.0, 5.0, 10.0, 40.0), y=(y,) * 4, z=(1.2,) * 4)
                for y in (-5.4, -1.8, 1.8, 5.4))
  return SimpleNamespace(frameId=frame_id, timestampEof=frame_id * 50_000_000,
                         laneLines=lines, laneLineProbs=probabilities)


def shifted_model_fixture(frame_id: int):
  lines = tuple(SimpleNamespace(x=(0.0, 5.0, 10.0, 40.0), y=(y,) * 4, z=(1.2,) * 4)
                for y in (-1.8, 1.8, 5.4, 9.0))
  return SimpleNamespace(frameId=frame_id, timestampEof=frame_id * 50_000_000,
                         laneLines=lines, laneLineProbs=(0.9, 0.9, 0.9, 0.9))


def test_ui_bridge_runs_at_four_hz_and_retains_last_result_between_frames():
  bridge = LaneTopologyUIBridge(frame_divisor=5)
  assert bridge.update(model_fixture(1)) is None
  result = bridge.update(model_fixture(5))
  assert result is not None
  assert result.visible_lane_count == 3
  assert result.ego_lane_index_from_left == 1
  assert bridge.update(model_fixture(6)) is result


def test_ui_bridge_fails_closed_on_malformed_model_message():
  bridge = LaneTopologyUIBridge(frame_divisor=1)
  assert bridge.update(SimpleNamespace(frameId=1, timestampEof=1)) is None
  assert bridge.last_error is not None


def test_ui_bridge_reset_drops_stale_onroad_state():
  bridge = LaneTopologyUIBridge(frame_divisor=1)
  assert bridge.update(model_fixture(1)) is not None
  bridge.reset()
  assert bridge.current is None


def test_single_frame_ego_source_pair_flicker_does_not_clear_marking_history():
  bridge = LaneTopologyUIBridge(frame_divisor=1)
  for frame_id in range(1, 5):
    bridge.update(model_fixture(frame_id))
  assert bridge.ego_source_ids == (1, 2)
  bridge.marking_types[1] = LaneMarkingType.dashed

  bridge.update(shifted_model_fixture(5))

  assert bridge.ego_source_ids == (1, 2)
  assert bridge.marking_types[1] == LaneMarkingType.dashed


def test_ego_markings_report_known_side_when_opposite_side_is_unknown():
  bridge = LaneTopologyUIBridge(frame_divisor=1)
  for frame_id in range(1, 5):
    bridge.update(model_fixture(frame_id))
  bridge.marking_types[1] = LaneMarkingType.unknown
  bridge.marking_types[2] = LaneMarkingType.dashed
  bridge.update(model_fixture(5))

  assert bridge.ego_marking_types() == (LaneMarkingType.unknown, LaneMarkingType.dashed)


def test_visionbuf_luma_returns_only_visible_width():
  frame = SimpleNamespace(width=6, height=4, stride=8, data=bytes(range(48)))
  luma = visionbuf_luma(frame)
  assert luma.shape == (4, 6)
  assert luma[1].tolist() == [8, 9, 10, 11, 12, 13]


def test_ui_bridge_accumulates_metric_dashed_and_solid_evidence():
  bridge = LaneTopologyUIBridge(frame_divisor=1)
  xs = tuple(np.arange(0.0, 61.0, 1.0))
  lines = tuple(SimpleNamespace(x=xs, y=(y,) * len(xs), z=(1.0,) * len(xs)) for y in (-30.0, -10.0, 10.0, 30.0))
  image = np.full((100, 300), 30, dtype=np.uint8)
  image[57:64, 20:201] = 230  # source 2: solid
  for start in range(5, 50, 9):
    image[37:44, start * 4:(start + 3) * 4] = 230  # source 1: 3 m line / 6 m gap
  camera_from_calib = np.array(((4.0, 0.0, 0.0), (0.0, 1.0, 50.0), (0.0, 0.0, 1.0)))
  for frame_id in range(1, 15):
    model = SimpleNamespace(frameId=frame_id, timestampEof=frame_id * 50_000_000, laneLines=lines, laneLineProbs=(0.1, 0.9, 0.9, 0.1))
    bridge.update(model)
    assert bridge.update_image(frame_id, image, camera_from_calib)
  bridge.update(SimpleNamespace(frameId=15, timestampEof=750_000_000, laneLines=lines, laneLineProbs=(0.1, 0.9, 0.9, 0.1)))
  assert bridge.marking_types[1] == LaneMarkingType.dashed
  assert bridge.marking_types[2] == LaneMarkingType.solid


def test_control_observer_classifies_only_the_current_ego_boundaries():
  bridge = LaneTopologyUIBridge(frame_divisor=1)
  xs = tuple(np.arange(0.0, 61.0, 1.0))
  lines = tuple(SimpleNamespace(x=xs, y=(y,) * len(xs), z=(1.0,) * len(xs)) for y in (-30.0, -10.0, 10.0, 30.0))
  image = np.full((100, 300), 30, dtype=np.uint8)
  for row in (20, 40, 60, 80):
    image[row - 3:row + 4, 20:201] = 230
  camera_from_calib = np.array(((4.0, 0.0, 0.0), (0.0, 1.0, 50.0), (0.0, 0.0, 1.0)))

  for frame_id in range(1, 15):
    model = SimpleNamespace(frameId=frame_id, timestampEof=frame_id * 50_000_000, laneLines=lines, laneLineProbs=(0.9,) * 4)
    bridge.update(model)
    assert bridge.update_image(frame_id, image, camera_from_calib)

  assert bridge.ego_source_ids == (1, 2)
  assert bridge.marking_types[0] == LaneMarkingType.unknown
  assert bridge.marking_types[3] == LaneMarkingType.unknown
  assert bridge.marking_evidence[0].sample_count == 0
  assert bridge.marking_evidence[3].sample_count == 0


def test_observer_does_not_restore_expired_type_with_geometry_tracker_votes():
  bridge = LaneTopologyUIBridge(frame_divisor=1)
  for frame_id in range(1, 5):
    bridge.update(model_fixture(frame_id))
  for frame_id in range(5, 15):
    bridge.marking_types[1] = LaneMarkingType.solid
    bridge.marking_types[2] = LaneMarkingType.dashed
    bridge.update(model_fixture(frame_id))
  assert bridge.ego_marking_types() == (LaneMarkingType.solid, LaneMarkingType.dashed)

  bridge.marking_types[1] = LaneMarkingType.unknown
  bridge.update(model_fixture(15))

  assert bridge.ego_marking_types() == (LaneMarkingType.unknown, LaneMarkingType.dashed)
