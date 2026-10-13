#!/usr/bin/env python3
"""Compare a lane-topology replay report with independent human labels."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any


GROUND_TRUTH_SCHEMA = "lane-marking-ground-truth-v1"
EXPECTED_TYPES = frozenset(("solid", "dashed"))
PREDICTED_TYPES = frozenset(("unknown", *EXPECTED_TYPES))


def _summary(pairs: list[tuple[str, str]]) -> dict[str, Any]:
  confusion: dict[str, Counter[str]] = defaultdict(Counter)
  for expected, predicted in pairs:
    confusion[expected][predicted] += 1
  labeled = len(pairs)
  known = sum(predicted != "unknown" for _, predicted in pairs)
  correct = sum(expected == predicted for expected, predicted in pairs)
  return {
    "labeled": labeled,
    "known": known,
    "correct": correct,
    "coverage": known / labeled if labeled else 0.0,
    "selective_accuracy": correct / known if known else 0.0,
    "end_to_end_accuracy": correct / labeled if labeled else 0.0,
    "solid_as_dashed": confusion["solid"]["dashed"],
    "dashed_as_solid": confusion["dashed"]["solid"],
    "confusion": {
      expected: {predicted: confusion[expected][predicted] for predicted in sorted(PREDICTED_TYPES)}
      for expected in sorted(EXPECTED_TYPES)
    },
  }


def evaluate_labels(report: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
  if ground_truth.get("schema") != GROUND_TRUTH_SCHEMA:
    raise ValueError("unsupported ground-truth schema")
  if ground_truth.get("segment") != report.get("segment"):
    raise ValueError("ground-truth segment does not match replay report")
  records = {record["frame_index"]: record for record in report.get("records", [])}
  pairs: list[tuple[str, str]] = []
  by_condition: dict[str, list[tuple[str, str]]] = defaultdict(list)
  seen: set[tuple[int, int]] = set()
  for label in ground_truth.get("labels", []):
    frame_index = label.get("frame_index")
    source_id = label.get("source_id")
    expected = label.get("expected")
    condition = label.get("condition", "unspecified")
    if not isinstance(frame_index, int) or frame_index not in records:
      raise ValueError("ground-truth frame is missing from replay report")
    if not isinstance(source_id, int) or not 0 <= source_id < 4:
      raise ValueError("ground-truth source_id must be in [0, 3]")
    if expected not in EXPECTED_TYPES:
      raise ValueError("ground-truth expected type must be solid or dashed")
    if not isinstance(condition, str) or not condition:
      raise ValueError("ground-truth condition must be a non-empty string")
    key = (frame_index, source_id)
    if key in seen:
      raise ValueError("duplicate ground-truth frame/source label")
    seen.add(key)
    predicted = records[frame_index]["stable_markings"][source_id]
    if predicted not in PREDICTED_TYPES:
      raise ValueError("replay report contains an unsupported marking type")
    pair = (expected, predicted)
    pairs.append(pair)
    by_condition[condition].append(pair)

  result = _summary(pairs)
  result["schema"] = "lane-marking-evaluation-v1"
  result["segment"] = report.get("segment")
  result["by_condition"] = {condition: _summary(values) for condition, values in sorted(by_condition.items())}
  return result


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--report", type=Path, required=True)
  parser.add_argument("--labels", type=Path, required=True)
  args = parser.parse_args()
  report = json.loads(args.report.read_text())
  ground_truth = json.loads(args.labels.read_text())
  print(json.dumps(evaluate_labels(report, ground_truth), indent=2, sort_keys=True))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
