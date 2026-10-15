#!/usr/bin/env python3
"""Audit primary-model lane edge evidence from an exported geometry file.

``tools/inspect_primary_lane_edges.py`` exports real modelV2 geometry and one
candidate per frame. This tool re-reads that export and reports *why* frames are
rejected, layer by layer, instead of only the first reason that fires. That
matters because the confidence gates short-circuit: a report of
``uncertainRoadEdges`` everywhere hides whether the geometry below it would ever
close, and relaxing a threshold that is not the real blocker would look like
progress.

It calls the shipped ``primary_edges.primary_edge_candidate`` for every layer, so
the audit cannot drift from the code it audits. Offline only: it reads one file
and touches no capture device, log stream, message bus, parameter or vehicle
interface.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterator

from openpilot.sunnypilot.lane_topology import primary_edges

SCHEMA = "primary-edge-diagnostic-v1"
STD_THRESHOLDS = (0.35, 0.5, 0.7, 1.0, 1.5, 2.0)
MAX_FRAMES = 200_000


class _Line:
  def __init__(self, curve: dict) -> None:
    self.x, self.y = curve["x"], curve["y"]


class _Model:
  def __init__(self, model: dict) -> None:
    self.laneLines = [_Line(curve) for curve in model["laneLines"]]
    self.roadEdges = [_Line(curve) for curve in model["roadEdges"]]
    self.laneLineProbs = model["laneLineProbs"]
    self.roadEdgeStds = model["roadEdgeStds"]


@contextmanager
def _gates(*, std: float, prob: float) -> Iterator[None]:
  """Temporarily relax the shipped gates so the layer below them becomes visible."""
  original = (primary_edges.MAX_EDGE_STD_M, primary_edges.MIN_LINE_PROB)
  primary_edges.MAX_EDGE_STD_M, primary_edges.MIN_LINE_PROB = std, prob
  try:
    yield
  finally:
    primary_edges.MAX_EDGE_STD_M, primary_edges.MIN_LINE_PROB = original


def _percentile(values: list[float], fraction: float) -> float:
  ordered = sorted(values)
  return ordered[min(len(ordered) - 1, max(0, int(fraction * len(ordered))))]


def load_records(path: Path) -> list[dict]:
  records = []
  with path.open() as source:
    for line in source:
      if not line.strip():
        continue
      record = json.loads(line)
      if record.get("schema") != SCHEMA:
        raise ValueError("unsupported diagnostic schema")
      if not isinstance(record.get("model"), dict):
        raise ValueError("frame is missing its model geometry")
      records.append(record)
      if len(records) > MAX_FRAMES:
        raise ValueError("too many frames")
  if not records:
    raise ValueError("no frames to audit")
  return records


def _reasons(models: list[_Model], *, std: float, prob: float) -> dict[str, int]:
  with _gates(std=std, prob=prob):
    counts: dict[str, int] = {}
    for model in models:
      reason = primary_edges.primary_edge_candidate(model).reason
      counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def audit_records(records: list[dict]) -> dict[str, Any]:
  models = [_Model(record["model"]) for record in records]
  left = [float(record["model"]["roadEdgeStds"][0]) for record in records]
  right = [float(record["model"]["roadEdgeStds"][1]) for record in records]
  worst = [max(a, b) for a, b in zip(left, right, strict=True)]
  slots = list(zip(*[record["model"]["laneLineProbs"] for record in records], strict=True))

  with _gates(std=math.inf, prob=0.0):
    candidates = [primary_edges.primary_edge_candidate(model) for model in models]
  widths = [candidate.lane_width_m for candidate in candidates if candidate.lane_width_m is not None]
  pairs: dict[str, int] = {}
  for candidate in candidates:
    key = f"{candidate.candidate_index}/{candidate.candidate_count}"
    pairs[key] = pairs.get(key, 0) + 1

  return {
    "frames": len(records),
    "road_edge_std": {
      "left_p10_p50_p90": [_percentile(left, 0.1), _percentile(left, 0.5), _percentile(left, 0.9)],
      "right_p10_p50_p90": [_percentile(right, 0.1), _percentile(right, 0.5), _percentile(right, 0.9)],
      "frames_both_within": {
        str(threshold): sum(1 for value in worst if value <= threshold) for threshold in STD_THRESHOLDS
      },
    },
    "lane_line_prob": [
      {
        "slot": slot,
        "median": statistics.median(values),
        "fraction_at_least_config": sum(1 for v in values if v >= primary_edges.MIN_LINE_PROB) / len(values),
      }
      for slot, values in enumerate(slots)
    ],
    "reasons": {
      "configured_gates": _reasons(models, std=primary_edges.MAX_EDGE_STD_M, prob=primary_edges.MIN_LINE_PROB),
      "road_edge_std_gate_removed": _reasons(models, std=math.inf, prob=primary_edges.MIN_LINE_PROB),
      "confidence_gates_removed": _reasons(models, std=math.inf, prob=0.0),
    },
    "with_confidence_gates_removed": {
      "frames_with_any_candidate": sum(1 for c in candidates if c.candidate_index is not None),
      "candidate_index_slash_count": dict(sorted(pairs.items())),
      "ego_lane_width_m_p10_p50_p90": (
        [_percentile(widths, 0.1), _percentile(widths, 0.5), _percentile(widths, 0.9)] if widths else None
      ),
    },
  }


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("geometry", type=Path, help="JSONL from tools/inspect_primary_lane_edges.py")
  parser.add_argument("--output", type=Path, help="write the audit JSON here instead of stdout")
  parser.add_argument("--require-candidate", action="store_true",
                      help="exit 2 when no frame yields a candidate even with the gates removed")
  args = parser.parse_args()

  audit = audit_records(load_records(args.geometry))
  text = json.dumps(audit, indent=2, sort_keys=True)
  if args.output:
    args.output.write_text(text + "\n")
  print(text)
  if args.require_candidate and audit["with_confidence_gates_removed"]["frames_with_any_candidate"] == 0:
    return 2
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
