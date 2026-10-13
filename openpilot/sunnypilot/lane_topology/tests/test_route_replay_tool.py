import ast
from pathlib import Path

import cv2
import numpy as np

from openpilot.sunnypilot.lane_topology.tests.test_ui_bridge import model_fixture
from tools.replay_primary_lane_topology import _calibration_at, decoded_luma, ReplayObserver, replay_record


ROOT = Path(__file__).resolve().parents[4]


def test_route_replay_tool_is_shadow_only_and_requires_synchronized_inputs():
  source = (ROOT / "tools/replay_primary_lane_topology.py").read_text()
  ast.parse(source)
  assert "modelV2" in source
  assert "qNarrowRoadEncodeIdx" in source
  assert "qcamera.ts" in source
  assert "--video-name" in source
  assert "--blur-sigma" in source
  assert "--disable-adaptive-marking" in source
  assert "--disable-partial-dashed" in source
  assert "PubMaster" not in source
  assert "Params" not in source
  assert "sendcan" not in source


def test_replay_uses_decoded_y_plane_instead_of_brightest_color_channel():
  frame = np.zeros((4, 6, 3), dtype=np.uint8)
  frame[:, :2] = (255, 0, 0)
  frame[:, 2:4] = (0, 255, 0)
  frame[:, 4:] = (0, 0, 255)
  luma = decoded_luma(frame)
  assert luma.shape == (4, 6)
  assert np.array_equal(luma, cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)[:4])
  assert not np.array_equal(luma, np.max(frame, axis=2))


def test_replay_geometry_runs_between_images_and_publishes_evidence_freshness():
  replay = ReplayObserver(stride=2, adaptive_marking=False, partial_dashed=False)
  image = np.zeros((100, 300), dtype=np.uint8)
  camera = np.array(((4.0, 0.0, 0.0), (0.0, 1.0, 50.0), (0.0, 0.0, 1.0)))
  image_frames = []
  for frame_id in range(1, 7):
    model = model_fixture(frame_id)
    publication = replay.update(
      model, now_ns=model.timestampEof + 10_000_000, image=image,
      image_frame_id=frame_id, image_mono_time=model.timestampEof, camera_from_calib=camera,
    )
    assert int(publication.laneTopologyStateSP.frameId) == frame_id
    if replay.image_processed:
      image_frames.append(frame_id)
  assert image_frames == [2, 4, 6]
  record = replay_record(replay, model, publication, frame_index=6)
  assert len(record["stable_markings"]) == len(record["frame_markings"]) == 4
  assert len(record["marking_evidence"]) == 4
  assert record["publication"]["validForControl"]
  assert not record["publication"]["leftEvidenceValid"]
  assert record["publication"]["leftRawMarking"] == "unknown"

  # A missing camera cannot freeze geometry or turn the retained evidence fresh.
  for frame_id in range(7, 18):
    model = model_fixture(frame_id)
    publication = replay.update(model, now_ns=model.timestampEof + 10_000_000, camera_from_calib=camera)
  assert int(publication.laneTopologyStateSP.frameId) == 17
  assert int(publication.laneTopologyStateSP.imageFrameId) == 6
  assert publication.laneTopologyStateSP.stale
  assert not publication.laneTopologyStateSP.validForControl


def test_replay_does_not_borrow_future_or_invalid_calibration():
  calibration = np.zeros(3)
  history = [(100, calibration), (200, None)]
  assert _calibration_at(history, 99) is None
  assert _calibration_at(history, 150) is calibration
  assert _calibration_at(history, 200) is None
