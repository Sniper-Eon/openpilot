#!/usr/bin/env python3
from __future__ import annotations

import time

import numpy as np

from msgq.visionipc import VisionIpcClient
from openpilot.cereal import log, messaging
from openpilot.cereal.visionipc import VisionStreamType
from openpilot.common.swaglog import cloudlog
from openpilot.common.transformations.camera import DEVICE_CAMERAS, view_frame_from_device_frame
from openpilot.common.transformations.orientation import rot_from_euler
from openpilot.sunnypilot.lane_topology.ui_bridge import LaneTopologyObserver, visionbuf_luma
from openpilot.sunnypilot.navassist.lane_publisher import build_lane_topology_message, MODEL_IMAGE_MAX_SKEW_NS


CALIBRATED = log.ExtrinsicsCalibration.Status.calibrated
IMAGE_CLASSIFIER_DIVISOR = 2


def services_healthy(sm, services: tuple[str, ...]) -> bool:
  return all(sm.seen[service] and sm.alive[service] and sm.valid[service] for service in services)


def _connect_camera() -> tuple[VisionIpcClient, VisionStreamType]:
  while True:
    streams = VisionIpcClient.available_streams("camerad", block=False)
    if streams:
      stream = (VisionStreamType.VISION_STREAM_NARROW_ROAD
                if VisionStreamType.VISION_STREAM_NARROW_ROAD in streams
                else VisionStreamType.VISION_STREAM_WIDE_ROAD)
      client = VisionIpcClient("camerad", stream, conflate=True)
      while not client.connect(False):
        time.sleep(0.1)
      return client, stream
    time.sleep(0.1)


def main() -> None:
  client, stream = _connect_camera()
  is_wide = stream == VisionStreamType.VISION_STREAM_WIDE_ROAD
  camera_state_service = "wideRoadCameraState" if is_wide else "narrowRoadCameraState"
  # Geometry follows modelV2 at 20 Hz; metric image evidence remains bounded to
  # about 10 Hz. This keeps the 150 ms model-age gate satisfiable without running
  # the image classifier on every frame.
  bridge = LaneTopologyObserver(frame_divisor=1)
  pm = messaging.PubMaster(["laneTopologyStateSP"])
  sm = messaging.SubMaster(
    ["modelV2", "extrinsicsCalibration", "deviceState", camera_state_service],
    poll="modelV2",
  )

  camera_from_calib: np.ndarray | None = None
  calibration_geometry_valid = False
  image_mono_time = 0
  image_model_mono_time = 0
  image_frame_id = 0
  previous_source_pair: tuple[int, int] | None = None
  source_pair_changed = False
  reported_error: str | None = None

  while True:
    # Time out at the advertised publish period so a stalled model still emits
    # an explicitly stale typed observation instead of leaving a latched value.
    sm.update(50)
    calibration_inputs_updated = any(sm.updated[service] for service in (
      "extrinsicsCalibration", "deviceState", camera_state_service,
    ))
    if calibration_inputs_updated and all(sm.seen[service] for service in (
      "extrinsicsCalibration", "deviceState", camera_state_service,
    )):
      calibration = sm["extrinsicsCalibration"]
      calibration_geometry_valid = bool(len(calibration.rpyCalib) == 3 and calibration.calStatus == CALIBRATED)
      try:
        if not calibration_geometry_valid:
          raise ValueError("calibration is not valid")
        device_camera = DEVICE_CAMERAS[(str(sm["deviceState"].deviceType), str(sm[camera_state_service].sensor))]
        intrinsics = device_camera.wide_road.intrinsics if is_wide else device_camera.narrow_road.intrinsics
        device_from_calib = rot_from_euler(calibration.rpyCalib)
        view_from_calib = view_frame_from_device_frame @ device_from_calib
        if is_wide and len(calibration.wideFromDeviceEuler) == 3:
          view_from_calib = view_frame_from_device_frame @ rot_from_euler(calibration.wideFromDeviceEuler) @ device_from_calib
        camera_from_calib = intrinsics @ view_from_calib
      except (KeyError, TypeError, ValueError):
        calibration_geometry_valid = False
        camera_from_calib = None

    calibration_inputs_healthy = services_healthy(
      sm, ("extrinsicsCalibration", "deviceState", camera_state_service),
    )
    calibration_valid = calibration_geometry_valid and calibration_inputs_healthy
    model_healthy = services_healthy(sm, ("modelV2",))
    if not model_healthy and bridge.current is not None:
      bridge.reset()
      previous_source_pair = None
      source_pair_changed = True
      image_mono_time = 0
      image_model_mono_time = 0
      image_frame_id = 0
    elif sm.updated["modelV2"]:
      bridge.update(sm["modelV2"])
      source_pair_changed = previous_source_pair is not None and bridge.ego_source_ids != previous_source_pair
      previous_source_pair = bridge.ego_source_ids

    frame = client.recv(timeout_ms=0)
    image_due = bridge.last_frame_id >= 0 and bridge.last_frame_id % IMAGE_CLASSIFIER_DIVISOR == 0
    frame_mono_time = int(client.timestamp_eof) if frame is not None else 0
    model_mono_time = int(getattr(bridge.model_v2, "timestampEof", 0)) if bridge.model_v2 is not None else 0
    image_model_synchronized = bool(
      frame_mono_time and model_mono_time and abs(frame_mono_time - model_mono_time) <= MODEL_IMAGE_MAX_SKEW_NS
    )
    if (frame is not None and image_due and calibration_valid and camera_from_calib is not None
        and image_model_synchronized and bridge.needs_image(frame.frame_id)):
      if bridge.update_image(frame.frame_id, visionbuf_luma(frame), camera_from_calib):
        image_mono_time = frame_mono_time
        image_model_mono_time = model_mono_time
        image_frame_id = int(client.frame_id)

    now_ns = time.monotonic_ns()
    message = build_lane_topology_message(
      bridge, now_ns=now_ns, image_mono_time=image_mono_time, image_frame_id=image_frame_id,
      image_model_mono_time=image_model_mono_time,
      calibration_valid=calibration_valid, source_pair_changed=source_pair_changed,
    )
    pm.send("laneTopologyStateSP", message)
    if bridge.last_error is not None and bridge.last_error != reported_error:
      cloudlog.error("lane_topologyd bridge failed: %s", bridge.last_error)
    reported_error = bridge.last_error


if __name__ == "__main__":
  main()
