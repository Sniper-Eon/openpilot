#!/usr/bin/env python3
"""Replay metric, typed lane boundaries through the absolute-lane evidence gate.

Input is a frames document (schema ``absolute-lane-frames-v1``) whose boundaries
are already in vehicle metres (``x`` forward, ``y`` left-positive) with a marking
type, which is exactly what ``LaneBoundaryObservation`` carries. Producing that
document from real images needs a metric boundary extractor plus a camera
calibration, and that extractor does not exist yet, so this tool is the offline
measurement step that is ready before the perception is.

Output is a decision report (schema ``absolute-lane-report-v1``) that
``tools/evaluate_absolute_lane_labels.py`` scores against human labels. Nothing
here reaches a vehicle: no camera, vision IPC, parameter or control imports.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from openpilot.sunnypilot.lane_topology.absolute_lane import AbsoluteLaneGate, RightEdgeAnchoredGate
from openpilot.sunnypilot.lane_topology.types import LaneBoundary, LaneMarkingType, LaneTopologyState

FRAMES_SCHEMA = "absolute-lane-frames-v1"
BOTH_EDGES = "bothEdges"
LANE_ANCHOR = "laneAnchor"
GATES = (BOTH_EDGES, LANE_ANCHOR)
REPORT_SCHEMA = "absolute-lane-report-v1"
MAX_FRAMES = 100_000


def _finite_number(value: object, *, name: str, low: float = -math.inf, high: float = math.inf) -> float:
  if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
    raise ValueError(f'{name} must be a finite number within [{low}, {high}]')
  return float(value)


def parse_marking_type(value: object) -> LaneMarkingType:
  if not isinstance(value, str) or value not in LaneMarkingType.__members__:
    raise ValueError(f'unknown marking type: {value!r}')
  return LaneMarkingType[value]


def parse_topology_state(value: object) -> LaneTopologyState:
  if value is None:
    return LaneTopologyState.normal
  if not isinstance(value, str) or value not in LaneTopologyState.__members__:
    raise ValueError(f'unknown topology state: {value!r}')
  return LaneTopologyState[value]


def boundary_from_json(record: object) -> LaneBoundary:
  if not isinstance(record, dict):
    raise ValueError('boundary must be an object')
  track_id = record.get('track_id')
  if type(track_id) is not int or track_id < 0:
    raise ValueError('boundary needs a non-negative integer track_id')
  points = record.get('points')
  if not isinstance(points, list) or len(points) < 2:
    raise ValueError('boundary needs at least two points')
  parsed: list[tuple[float, float]] = []
  for point in points:
    if not isinstance(point, list) or len(point) != 2:
      raise ValueError('each boundary point must be [x, y]')
    parsed.append((_finite_number(point[0], name='point x'), _finite_number(point[1], name='point y')))
  confidence = _finite_number(record.get('confidence', 0.0), name='confidence', low=0.0, high=1.0)
  visible = record.get('visible', True)
  if type(visible) is not bool:
    raise ValueError('visible must be a boolean')
  return LaneBoundary(track_id, tuple(parsed), parse_marking_type(record.get('marking_type', 'unknown')),
                      confidence, visible=visible)


def replay_frames(document: object, *, gate=None) -> dict[str, Any]:
  if not isinstance(document, dict) or document.get('schema') != FRAMES_SCHEMA:
    raise ValueError('unsupported frames schema')
  segment = document.get('segment')
  if not isinstance(segment, str) or not segment:
    raise ValueError('frames document needs a segment')
  frames = document.get('frames')
  if not isinstance(frames, list) or not frames:
    raise ValueError('frames document needs frames')
  if len(frames) > MAX_FRAMES:
    raise ValueError('too many frames')
  session_id = document.get('session_id', 'replay')
  if not isinstance(session_id, str) or not session_id:
    raise ValueError('session_id must be a non-empty string')
  route_revision = document.get('route_revision', 0)
  if type(route_revision) is not int or route_revision < 0:
    raise ValueError('route_revision must be a non-negative integer')

  # The anchored gate needs the map total; the both-edge gate needs two edges.
  which = document.get('gate', BOTH_EDGES)
  if which not in GATES:
    raise ValueError('unsupported gate')
  lane_gate = gate if gate is not None else (
    RightEdgeAnchoredGate() if which == LANE_ANCHOR else AbsoluteLaneGate())
  document_total = document.get('lane_total')
  records: list[dict[str, Any]] = []
  for index, frame in enumerate(frames):
    if not isinstance(frame, dict):
      raise ValueError('frame must be an object')
    frame_id = frame.get('frame_id', index)
    if type(frame_id) is not int or frame_id < 0:
      raise ValueError('frame_id must be a non-negative integer')
    capture = frame.get('capture_mono_ns')
    if type(capture) is not int or capture < 1:
      raise ValueError('capture_mono_ns must be a positive integer')
    frame_session = frame.get('session_id', session_id)
    frame_revision = frame.get('route_revision', route_revision)
    if not isinstance(frame_session, str) or not frame_session:
      raise ValueError('frame session_id must be a non-empty string')
    if type(frame_revision) is not int or frame_revision < 0:
      raise ValueError('frame route_revision must be a non-negative integer')
    boundaries = tuple(boundary_from_json(item) for item in frame.get('boundaries', []))
    if len({boundary.track_id for boundary in boundaries}) != len(boundaries):
      raise ValueError('duplicate track_id within one frame')
    topology_state = parse_topology_state(frame.get('topology_state'))
    ego_y_m = _finite_number(frame.get('ego_y_m', 0.0), name='ego_y_m')
    if which == LANE_ANCHOR:
      lane_total = frame.get('lane_total', document_total)
      if lane_total is not None and type(lane_total) is not int:
        raise ValueError('lane_total must be an integer when present')
      decision = lane_gate.update(
        boundaries,
        right_anchor_track_id=frame.get('right_anchor_track_id', -1),
        lane_total=lane_total,
        frame_id=frame_id,
        timestamp_ns=capture,
        session_id=frame_session,
        route_revision=frame_revision,
        topology_state=topology_state,
        ego_y_m=ego_y_m,
      )
    else:
      decision = lane_gate.update(
        boundaries,
        left_edge_track_id=frame.get('left_edge_track_id', -1),
        right_edge_track_id=frame.get('right_edge_track_id', -1),
        frame_id=frame_id,
        timestamp_ns=capture,
        session_id=frame_session,
        route_revision=frame_revision,
        topology_state=topology_state,
        ego_y_m=ego_y_m,
      )
    records.append({
      'frame_index': frame_id,
      'valid': decision.valid,
      'lane_index': decision.lane_index,
      'lane_count': decision.lane_count,
      'stable_samples': decision.stable_samples,
      'capture_mono_ns': decision.capture_mono_ns,
      'reason': decision.reason,
    })
  return {'schema': REPORT_SCHEMA, 'segment': segment, 'gate': which, 'records': records}


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--frames', type=Path, required=True)
  parser.add_argument('--report', type=Path, required=True)
  parser.add_argument('--labels', type=Path, help='optional human labels; prints the scored metrics')
  args = parser.parse_args()

  report = replay_frames(json.loads(args.frames.read_text()))
  args.report.parent.mkdir(parents=True, exist_ok=True)
  args.report.write_text(json.dumps(report, indent=2, sort_keys=True))

  summary: dict[str, Any] = {
    'frames': len(report['records']),
    'confirmed': sum(1 for record in report['records'] if record['valid']),
  }
  if args.labels is not None:
    from tools.evaluate_absolute_lane_labels import evaluate_absolute_labels
    summary['metrics'] = evaluate_absolute_labels(report, json.loads(args.labels.read_text()))
  print(json.dumps(summary, indent=2, sort_keys=True))
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
