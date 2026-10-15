#!/usr/bin/env python3
"""Score an absolute-lane decision report against independent human labels.

A system that never answers is useless but safe, while a single confident wrong
index is worse than an unknown, so coverage and false positives are reported
separately and never averaged into one number.

Neither input can be produced from the 2026-10-15 road test: that recording kept
scalar diagnostics only, with no boundary geometry and no images. This tool is
the missing measurement step for a labelled image or video segment.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "absolute-lane-report-v1"
GROUND_TRUTH_SCHEMA = "lane-position-ground-truth-v1"


def _rate(numerator: int, denominator: int) -> float:
  return numerator / denominator if denominator else 0.0


def evaluate_absolute_labels(report: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
  if report.get("schema") != REPORT_SCHEMA:
    raise ValueError("unsupported report schema")
  if ground_truth.get("schema") != GROUND_TRUTH_SCHEMA:
    raise ValueError("unsupported ground-truth schema")
  if ground_truth.get("segment") != report.get("segment"):
    raise ValueError("ground-truth segment does not match report")

  predictions = {record["frame_index"]: record for record in report.get("records", [])}
  labeled = known = correct = false_positives = missed = count_mismatches = 0
  unknown_reasons: Counter[str] = Counter()
  false_positive_pairs: dict[int, Counter[int]] = defaultdict(Counter)

  for label in ground_truth.get("labels", []):
    frame_index = label["frame_index"]
    record = predictions.get(frame_index)
    if record is None:
      continue
    truth_index = label.get("lane_index")
    truth_count = label.get("lane_count")
    predicted_valid = bool(record.get("valid"))
    predicted_index = record.get("lane_index") if predicted_valid else None

    labeled += 1
    if not predicted_valid:
      unknown_reasons[str(record.get("reason", "unknown"))] += 1
      if truth_index is not None:
        missed += 1
      continue

    known += 1
    if predicted_index == truth_index:
      correct += 1
    else:
      false_positives += 1
      if truth_index is not None and predicted_index is not None:
        false_positive_pairs[truth_index][predicted_index] += 1
    if truth_count is not None and record.get("lane_count") is not None and record["lane_count"] != truth_count:
      count_mismatches += 1

  return {
    "labeled": labeled,
    "known": known,
    "correct": correct,
    "coverage": _rate(known, labeled),
    "unknown_rate": _rate(labeled - known, labeled),
    "selective_accuracy": _rate(correct, known),
    "end_to_end_accuracy": _rate(correct, labeled),
    "false_positives": false_positives,
    "false_positive_rate": _rate(false_positives, known),
    "missed": missed,
    "count_mismatches": count_mismatches,
    "unknown_reasons": dict(sorted(unknown_reasons.items())),
    "false_positive_pairs": {
      str(truth): {str(predicted): count for predicted, count in sorted(pairs.items())}
      for truth, pairs in sorted(false_positive_pairs.items())
    },
  }


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--report", type=Path, required=True)
  parser.add_argument("--labels", type=Path, required=True)
  parser.add_argument("--fail-on-false-positive", action="store_true",
                      help="exit 2 when any labelled frame produced a wrong confirmed index")
  args = parser.parse_args()

  metrics = evaluate_absolute_labels(json.loads(args.report.read_text()),
                                     json.loads(args.labels.read_text()))
  print(json.dumps(metrics, indent=2, sort_keys=True))
  if args.fail_on_false_positive and metrics["false_positives"]:
    return 2
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
