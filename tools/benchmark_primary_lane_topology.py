#!/usr/bin/env python3
"""Dependency-free CPU benchmark for reusing primary model lane lines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np

from openpilot.sunnypilot.lane_topology.geometry import analyze_lane_topology
from openpilot.sunnypilot.lane_topology.primary_model import model_v2_to_observations


def percentile(values: list[float], q: float) -> float:
  return float(np.percentile(np.asarray(values, dtype=np.float64), q * 100.0))


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--runs", type=int, default=10000)
  parser.add_argument("--report", type=Path, required=True)
  args = parser.parse_args()
  if args.runs <= 0:
    raise ValueError("runs must be positive")
  if args.report.exists():
    raise FileExistsError(args.report)

  lines = tuple(SimpleNamespace(x=(0.0, 5.0, 10.0, 20.0, 40.0, 80.0), y=(y,) * 6, z=(0.0,) * 6)
                for y in (5.4, 1.8, -1.8, -5.4))
  model = SimpleNamespace(laneLines=lines, laneLineProbs=(0.9, 0.95, 0.95, 0.9))
  latencies = []
  last = None
  for frame_id in range(args.runs):
    started = time.perf_counter()
    observations = model_v2_to_observations(model)
    last = analyze_lane_topology(observations, frame_id=frame_id, timestamp_ns=frame_id * 50_000_000)
    latencies.append((time.perf_counter() - started) * 1000.0)
  assert last is not None
  if (last.boundary_count_visible, last.visible_lane_count, last.ego_lane_index_from_left, last.ego_lane_index_from_right) != (4, 3, 1, 1):
    raise RuntimeError(f"unexpected topology result: {last}")

  report = {
    "schema": "primary-model-lane-topology-cpu-benchmark-v1",
    "status": "PASS",
    "source": "existing modelV2 laneLines/laneLineProbs",
    "runs": args.runs,
    "latency_ms": {
      "mean": sum(latencies) / len(latencies),
      "p50": percentile(latencies, 0.50),
      "p95": percentile(latencies, 0.95),
      "p99": percentile(latencies, 0.99),
      "min": min(latencies),
      "max": max(latencies),
    },
    "result": {
      "visible_boundaries": last.boundary_count_visible,
      "visible_lanes": last.visible_lane_count,
      "ego_lane_from_left": last.ego_lane_index_from_left,
      "ego_lane_from_right": last.ego_lane_index_from_right,
    },
    "gpu_used": False,
    "production_hooked": False,
  }
  args.report.parent.mkdir(parents=True, exist_ok=True)
  with args.report.open("x") as output:
    json.dump(report, output, indent=2, sort_keys=True)
    output.write("\n")
  print(json.dumps(report, indent=2, sort_keys=True))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
