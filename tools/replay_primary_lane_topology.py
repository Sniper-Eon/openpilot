#!/usr/bin/env python3
"""Replay rlog/modelV2 and decoded qcamera Y through the production lane observer."""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import json
from pathlib import Path

import cv2
import numpy as np

from openpilot.common.transformations.camera import DEVICE_CAMERAS, view_frame_from_device_frame
from openpilot.common.transformations.orientation import rot_from_euler
from openpilot.sunnypilot.lane_topology.metric_marking import marking_sampling_parameters, project_model_lane_metric_samples
from openpilot.sunnypilot.lane_topology.types import LaneMarkingType
from openpilot.sunnypilot.lane_topology.ui_bridge import LaneTopologyObserver
from openpilot.sunnypilot.navassist.lane_publisher import build_lane_topology_message, MODEL_IMAGE_MAX_SKEW_NS
from openpilot.tools.lib.logreader import LogReader


TYPE_COLORS = {
  LaneMarkingType.unknown: (128, 128, 128),
  LaneMarkingType.solid: (0, 255, 0),
  LaneMarkingType.dashed: (0, 255, 255),
  LaneMarkingType.doubleSolid: (255, 0, 255),
  LaneMarkingType.doubleDashed: (255, 255, 0),
  LaneMarkingType.solidDashed: (0, 128, 255),
}


def _load_log(path: Path):
  models: dict[int, tuple[int, object]] = {}
  q_indices: list[object] = []
  calibrations: list[tuple[int, np.ndarray | None]] = []
  device_type = sensor = None
  for message in LogReader(str(path)):
    which = message.which()
    if which == "modelV2":
      models[int(message.modelV2.frameId)] = (int(message.logMonoTime), message.modelV2)
    elif which == "qNarrowRoadEncodeIdx":
      q_indices.append(message.qNarrowRoadEncodeIdx)
    elif which == "extrinsicsCalibration":
      calibration = message.extrinsicsCalibration
      rpy = (np.asarray(calibration.rpyCalib, dtype=np.float64)
             if str(calibration.calStatus) == "calibrated" and len(calibration.rpyCalib) == 3 else None)
      calibrations.append((int(message.logMonoTime), rpy))
    elif which == "deviceState" and device_type is None:
      device_type = str(message.deviceState.deviceType)
    elif which == "narrowRoadCameraState" and sensor is None:
      sensor = str(message.narrowRoadCameraState.sensor)
  if not models or not q_indices or not calibrations or device_type is None or sensor is None:
    raise RuntimeError("route is missing modelV2, qcamera index, calibrated extrinsics, or camera identity")
  q_indices.sort(key=lambda index: int(index.encodeId))
  calibrations.sort(key=lambda value: value[0])
  return models, q_indices, calibrations, device_type, sensor


def _calibration_at(calibrations: list[tuple[int, np.ndarray | None]], timestamp_ns: int) -> np.ndarray | None:
  timestamps = [value[0] for value in calibrations]
  index = bisect_right(timestamps, timestamp_ns) - 1
  return calibrations[index][1] if index >= 0 else None


def _camera_matrix(device_type: str, sensor: str, rpy_calib: np.ndarray,
                   q_width: int, q_height: int) -> np.ndarray:
  camera = DEVICE_CAMERAS[(device_type, sensor)].narrow_road
  intrinsics = camera.intrinsics.astype(np.float64)
  intrinsics[0] *= q_width / camera.width
  intrinsics[1] *= q_height / camera.height
  return intrinsics @ view_frame_from_device_frame @ rot_from_euler(rpy_calib)


def _counter_json(counter: Counter) -> dict[str, int]:
  return {str(key): value for key, value in sorted(counter.items(), key=lambda item: str(item[0]))}


def decoded_luma(frame_bgr: np.ndarray) -> np.ndarray:
  """Recover a decoded Y plane; compressed qcamera is not the native VisionBuf."""
  height, width = frame_bgr.shape[:2]
  if height % 2 or width % 2:
    raise ValueError("decoded YUV420 replay requires even video dimensions")
  return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2YUV_I420)[:height, :width]


class ReplayObserver:
  """Keep replay image metadata while the production observer owns all inference."""

  def __init__(self, *, stride: int = 2, adaptive_marking: bool = True, partial_dashed: bool = True):
    if stride <= 0:
      raise ValueError("stride must be positive")
    self.stride = stride
    self.observer = LaneTopologyObserver(frame_divisor=1, adaptive_marking=adaptive_marking, partial_dashed=partial_dashed)
    self.image_mono_time = 0
    self.image_model_mono_time = 0
    self.image_frame_id = 0
    self.image_processed = False

  def update(self, model, *, now_ns: int, image: np.ndarray | None = None, image_mono_time: int = 0,
             image_frame_id: int = 0, camera_from_calib: np.ndarray | None = None):
    previous_source_pair = self.observer.ego_source_ids
    self.observer.update(model)
    source_pair_changed = previous_source_pair is not None and self.observer.ego_source_ids != previous_source_pair
    self.image_processed = False
    model_mono_time = int(model.timestampEof)
    synchronized = bool(image_mono_time and model_mono_time and
                        abs(image_mono_time - model_mono_time) <= MODEL_IMAGE_MAX_SKEW_NS)
    if (image is not None and int(model.frameId) % self.stride == 0 and camera_from_calib is not None and synchronized):
      self.image_processed = self.observer.update_image(image_frame_id, image, camera_from_calib)
      if self.image_processed:
        self.image_mono_time = image_mono_time
        self.image_model_mono_time = model_mono_time
        self.image_frame_id = image_frame_id
    return build_lane_topology_message(
      self.observer, now_ns=now_ns, image_mono_time=self.image_mono_time, image_frame_id=self.image_frame_id,
      image_model_mono_time=self.image_model_mono_time, calibration_valid=camera_from_calib is not None,
      source_pair_changed=source_pair_changed,
    )


def replay_record(replay: ReplayObserver, model, publication, *, frame_index: int | None) -> dict:
  observer = replay.observer
  topology = observer.current
  state = publication.laneTopologyStateSP
  return {
    "frame_index": frame_index,
    "frame_id": int(model.frameId),
    "boundary_count": topology.boundary_count_visible if topology is not None else 0,
    "lane_count": int(state.visibleLaneCount),
    "ego_left": int(state.egoLaneIndexFromLeft),
    "ego_right": int(state.egoLaneIndexFromRight),
    "state": str(state.topologyState),
    "markings": [boundary.marking_type.name for boundary in topology.boundaries] if topology is not None else [],
    "stable_markings": [marking.name for marking in observer.marking_types],
    "frame_markings": [evidence.marking_type.name for evidence in observer.marking_evidence],
    "marking_evidence": [{
      "sample_count": evidence.sample_count,
      "confidence": evidence.confidence,
      "coverage": evidence.coverage,
      "transitions": evidence.transitions,
      "lit_runs": evidence.lit_runs,
      "max_internal_dark_gap_m": evidence.max_internal_dark_gap_m,
      "median_lit_run_m": evidence.median_lit_run_m,
      "complete_lit_runs": evidence.complete_lit_runs,
      "internal_dark_runs": evidence.internal_dark_runs,
      "run_regularity": evidence.run_regularity,
    } for evidence in observer.marking_evidence],
    "probabilities": [float(value) for value in model.laneLineProbs],
    "image_processed": replay.image_processed,
    "publication": {"message_valid": bool(publication.valid), **state.to_dict()},
    "observer_error": observer.last_error,
  }


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--segment-dir", type=Path, required=True)
  parser.add_argument("--video-name", default="qcamera.ts")
  parser.add_argument("--stride", type=int, default=2, help="classify images every Nth model frame; geometry updates every model frame")
  parser.add_argument("--blur-sigma", type=float, default=0.0, help="synthetic Gaussian blur for robustness A/B")
  parser.add_argument("--disable-adaptive-marking", action="store_true",
                      help="use only the original fixed contrast threshold")
  parser.add_argument("--disable-partial-dashed", action="store_true",
                      help="require three complete dash runs instead of low-confidence partial evidence")
  parser.add_argument("--report", type=Path, required=True)
  parser.add_argument("--overlay-dir", type=Path, required=True)
  parser.add_argument("--overlay-every", type=int, default=300)
  args = parser.parse_args()
  if args.stride <= 0 or args.overlay_every <= 0 or args.blur_sigma < 0.0:
    raise ValueError("stride and overlay-every must be positive")
  if args.report.exists():
    raise FileExistsError(args.report)
  rlog, video = args.segment_dir / "rlog.zst", args.segment_dir / args.video_name
  if not rlog.is_file() or not video.is_file():
    raise FileNotFoundError("segment directory must contain rlog.zst and qcamera.ts")

  models, q_indices, calibrations, device_type, sensor = _load_log(rlog)
  capture = cv2.VideoCapture(str(video))
  if not capture.isOpened():
    raise RuntimeError(f"cannot open {video}")
  width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
  center_radius, side_offset, search_radius = marking_sampling_parameters(width)
  marking_kwargs = {
    "center_radius": center_radius,
    "side_offset": side_offset,
    "search_radius": search_radius,
  }
  replay = ReplayObserver(stride=args.stride, adaptive_marking=not args.disable_adaptive_marking,
                          partial_dashed=not args.disable_partial_dashed)
  distributions = {name: Counter() for name in ("boundaries", "lanes", "ego_left", "ego_right", "state", "marking")}
  records = []
  exact_matches = missing_models = ego_transitions = image_updates = 0
  previous_ego: int | None = None
  args.overlay_dir.mkdir(parents=True, exist_ok=True)

  def process(model_entry, *, frame_index=None, frame_bgr=None, encode=None):
    nonlocal ego_transitions, previous_ego, image_updates
    model_time, model = model_entry
    rpy_calib = _calibration_at(calibrations, model_time)
    camera_from_calib = _camera_matrix(device_type, sensor, rpy_calib, width, height) if rpy_calib is not None else None
    luma = decoded_luma(frame_bgr) if frame_bgr is not None else None
    if luma is not None and args.blur_sigma:
      luma = cv2.GaussianBlur(luma, (0, 0), sigmaX=args.blur_sigma, sigmaY=args.blur_sigma)
    publication = replay.update(
      model, now_ns=model_time, image=luma, camera_from_calib=camera_from_calib,
      image_frame_id=int(encode.frameId) if encode is not None else 0,
      image_mono_time=int(encode.timestampEof) if encode is not None else 0,
    )
    image_updates += int(replay.image_processed)
    record = replay_record(replay, model, publication, frame_index=frame_index)
    for distribution, field in (("boundaries", "boundary_count"), ("lanes", "lane_count"),
                                ("ego_left", "ego_left"), ("ego_right", "ego_right"), ("state", "state")):
      distributions[distribution][record[field]] += 1
    distributions["marking"].update(record["markings"])
    if record["ego_left"] >= 0:
      if previous_ego is not None and record["ego_left"] != previous_ego:
        ego_transitions += 1
      previous_ego = record["ego_left"]
    records.append(record)

    if frame_bgr is not None and camera_from_calib is not None and frame_index % args.overlay_every == 0:
      overlay = frame_bgr.copy()
      for lane_index, lane in enumerate(model.laneLines):
        points = tuple((sample.u, sample.v) for sample in project_model_lane_metric_samples(
          lane, camera_from_calib, width, height, min_distance_m=3.0, max_distance_m=60.0,
          distance_step_m=1.0, image_margin_px=0.0,
        ))
        color = TYPE_COLORS[replay.observer.marking_types[lane_index]]
        pts = np.rint(points).astype(np.int32)
        for start, end in zip(pts, pts[1:], strict=False):
          cv2.line(overlay, tuple(start), tuple(end), color, 2)
      label = f"lanes={record['lane_count']} ego={record['ego_left']} state={record['state']}"
      cv2.putText(overlay, label, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2)
      cv2.putText(overlay, label, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 1)
      cv2.imwrite(str(args.overlay_dir / f"frame_{frame_index:04d}.png"), overlay)

  # Merge the camera index with the model stream. Missing camera frames must
  # not drop geometry updates or change the observer's temporal cadence.
  model_entries = iter(sorted(models.items()))
  pending = next(model_entries, None)
  frame_index = 0
  while frame_index < len(q_indices):
    ok, frame_bgr = capture.read()
    if not ok:
      break
    encode = q_indices[frame_index]
    frame_id = int(encode.frameId)
    while pending is not None and pending[0] < frame_id:
      process(pending[1])
      pending = next(model_entries, None)
    if pending is not None and pending[0] == frame_id:
      process(pending[1], frame_index=frame_index, frame_bgr=frame_bgr, encode=encode)
      exact_matches += 1
      pending = next(model_entries, None)
    else:
      missing_models += 1
    frame_index += 1
  while pending is not None:
    process(pending[1])
    pending = next(model_entries, None)
  capture.release()

  analyzed = len(records)
  report = {
    "schema": "primary-model-lane-topology-route-replay-v2",
    "status": "PASS" if analyzed else "FAIL",
    "segment": args.segment_dir.name,
    "source": {"rlog": str(rlog), "video": str(video), "device_type": device_type, "sensor": sensor},
    "video": {"width": width, "height": height, "decoded_frames": frame_index},
    "pipeline": "LaneTopologyObserver(frame_divisor=1) + build_lane_topology_message",
    "image_input": "decoded BGR to YUV_I420 Y plane; not native VisionBuf luma",
    "accuracy_validated": False,
    "marking_sampling": marking_kwargs,
    "synthetic_blur_sigma": args.blur_sigma,
    "adaptive_marking": not args.disable_adaptive_marking,
    "partial_dashed": not args.disable_partial_dashed,
    "stride": args.stride,
    "analyzed_frames": analyzed,
    "image_updates": image_updates,
    "model_frames_without_video": analyzed - exact_matches,
    "exact_model_frame_matches": exact_matches,
    "missing_model_frames": missing_models,
    "ego_index_transitions": ego_transitions,
    "distributions": {name: _counter_json(counter) for name, counter in distributions.items()},
    "records": records,
  }
  args.report.parent.mkdir(parents=True, exist_ok=True)
  with args.report.open("x") as output:
    json.dump(report, output, indent=2, sort_keys=True)
    output.write("\n")
  print(json.dumps({key: value for key, value in report.items() if key != "records"}, indent=2, sort_keys=True))
  return 0 if analyzed else 1


if __name__ == "__main__":
  raise SystemExit(main())
