#!/usr/bin/env python3
"""Export real model geometry and diagnostic lane candidates from local qlogs.

Offline only. Does not open camera IPC, publish messages, change parameters, or
write the absolute lane feedback file. The JSONL preserves geometry for review.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

from openpilot.sunnypilot.lane_topology.primary_edges import primary_edge_candidate


def json_safe(value):
  # Real logs can contain NaN. Preserve its position as null instead of writing
  # nonstandard JSON, inventing zero geometry, or losing the rest of the log.
  if isinstance(value, float) and not math.isfinite(value):
    return None
  if isinstance(value, dict):
    return {key: json_safe(item) for key, item in value.items()}
  if isinstance(value, (list, tuple)):
    return [json_safe(item) for item in value]
  return value


def inspect_events(events, output) -> dict:
  reasons, pairs = Counter(), Counter()
  total = 0
  for event in events:
    if event.which() != 'modelV2':
      continue
    model = event.modelV2
    candidate = primary_edge_candidate(model)
    record = {
      'schema': 'primary-edge-diagnostic-v1',
      'capture_mono_ns': int(model.timestampEof),
      'log_mono_ns': int(event.logMonoTime),
      'event_valid': bool(event.valid),
      'frame_id': int(model.frameId),
      'candidate': candidate.to_dict(),
      'model': {name: [curve.to_dict() for curve in getattr(model, name)] for name in ('laneLines', 'roadEdges')},
    }
    record['model'].update({name: list(getattr(model, name)) for name in ('laneLineProbs', 'roadEdgeStds')})
    output.write(json.dumps(json_safe(record), allow_nan=False) + '\n')
    total += 1
    reasons[candidate.reason] += 1
    if candidate.candidate_index is not None:
      pairs[f'{candidate.candidate_index}/{candidate.candidate_count}'] += 1
  return {'schema': 'primary-edge-summary-v1', 'model_frames': total,
          'reasons': dict(reasons), 'candidate_pairs': dict(pairs),
          'absolute_confirmations': 0, 'accuracy': None}


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('logs', type=Path, nargs='+')
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  from openpilot.cereal import log
  import zstandard

  def events():
    for path in args.logs:
      data = path.read_bytes()
      if path.suffix == '.zst':
        with zstandard.ZstdDecompressor().stream_reader(data) as reader:
          data = reader.read()
      yield from log.Event.read_multiple_bytes(data)

  with args.output.open('w') as output:
    summary = inspect_events(events(), output)
  print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
  main()
