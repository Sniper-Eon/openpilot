"""Bounded 1 Hz local wide-camera evidence, independent of hardware encoderd.

Frames retain device monotonic EOF times for alignment with the full rlog.
No model inference, vehicle parameters, network calls or control publishers.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import time
import uuid

DEFAULT_ROOT = Path('/data/media/0/lane-evidence')
MAX_BYTES = 512 * 1024 * 1024
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024


class FrameWriter:
  def __init__(self, root: Path = DEFAULT_ROOT, *, max_bytes: int = MAX_BYTES,
               rotate_seconds: float = 60, min_free_bytes: int = MIN_FREE_BYTES):
    self.root, self.max_bytes = root, max_bytes
    self.rotate_seconds, self.min_free_bytes = rotate_seconds, min_free_bytes
    self.stream = None
    self.partial = None
    self.opened = 0.0

  def prune(self, incoming: int) -> None:
    files = sorted((p for p in self.root.glob('wide-*')
                    if p.suffix in ('.jsonl', '.partial') and p != self.partial),
                   key=lambda p: p.stat().st_mtime_ns)
    total = sum(p.stat().st_size for p in files)
    total += self.partial.stat().st_size if self.partial is not None else 0
    while files and total + incoming > self.max_bytes:
      path = files.pop(0)
      total -= path.stat().st_size
      path.unlink()
    if total + incoming > self.max_bytes:
      self.close()
      raise OSError('lane evidence byte budget reached')

  def write(self, record: dict, *, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    data = (json.dumps(record, allow_nan=False, separators=(',', ':')) + '\n').encode()
    if len(data) > 1024 * 1024:
      raise ValueError('oversized evidence frame')
    self.root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(self.root).free < self.min_free_bytes:
      self.close()
      raise OSError('insufficient space for lane evidence')
    if self.stream is not None and now - self.opened >= self.rotate_seconds:
      self.close()
    self.prune(len(data))
    if self.stream is None:
      self.partial = self.root / f'wide-{time.time_ns()}-{uuid.uuid4().hex[:8]}.partial'
      self.stream = self.partial.open('xb')
      self.partial.chmod(0o600)
      self.opened = now
    self.stream.write(data)
    self.stream.flush()

  def close(self) -> None:
    if self.stream is not None:
      self.stream.close()
      self.partial.rename(self.partial.with_suffix('.jsonl'))
      self.stream, self.partial = None, None


def main() -> None:
  from msgq.visionipc import VisionIpcClient
  from openpilot.cereal import messaging
  from openpilot.cereal.visionipc import VisionStreamType
  from openpilot.common.swaglog import cloudlog
  from openpilot.sunnypilot.lane_topology.external.sender import export_nv12
  from openpilot.sunnypilot.navassist.diagnostics import finite_values

  client = VisionIpcClient('camerad', VisionStreamType.VISION_STREAM_WIDE_ROAD, conflate=True)
  writer = FrameWriter()
  sm = messaging.SubMaster(['modelV2', 'navAssistStateSP', 'extrinsicsCalibration', 'wideRoadCameraState'])
  next_sample, last_stamp, last_error = 0.0, 0, None
  try:
    while not client.connect(False):
      time.sleep(.5)
    while True:
      time.sleep(max(0.0, next_sample - time.monotonic()))
      next_sample = time.monotonic() + 1.0
      frame = client.recv(timeout_ms=200)
      sm.update(0)
      stamp = int(client.timestamp_eof) if frame is not None else 0
      now_ns = time.monotonic_ns()
      if frame is None or stamp <= last_stamp or not 0 <= now_ns - stamp < 500_000_000:
        continue
      last_stamp = stamp
      try:
        image = export_nv12(frame)
      except ValueError:
        continue
      record = {'schema': 'wide-lane-evidence-v1', 'capture_mono_ns': stamp,
                'recorded_mono_ns': now_ns, 'frame_id': int(client.frame_id),
                'source_width': int(frame.width), 'source_height': int(frame.height),
                'image': image, 'services': {}}
      for name in ('modelV2', 'navAssistStateSP', 'extrinsicsCalibration', 'wideRoadCameraState'):
        if sm.seen[name]:
          value = sm[name]
          # Only geometry and timing, rather than model raw tensors or leads.
          if name == 'modelV2':
            value = {'frameId': int(value.frameId), 'timestampEof': int(value.timestampEof),
                     'laneLines': [line.to_dict() for line in value.laneLines],
                     'roadEdges': [line.to_dict() for line in value.roadEdges],
                     'laneLineProbs': list(value.laneLineProbs), 'roadEdgeStds': list(value.roadEdgeStds)}
          else:
            value = value.to_dict()
          record['services'][name] = {'log_mono_ns': int(sm.logMonoTime[name]),
                                      'alive': bool(sm.alive[name]), 'valid': bool(sm.valid[name]), 'data': value}
      try:
        # Geometry occasionally contains NaN; preserve it as null, never zero.
        writer.write(finite_values(record))
        last_error = None
      except (OSError, ValueError) as error:
        if type(error).__name__ != last_error:
          cloudlog.error('local lane evidence write failed: %s', type(error).__name__)
          last_error = type(error).__name__
  except KeyboardInterrupt:
    pass
  finally:
    writer.close()


if __name__ == '__main__':
  main()
