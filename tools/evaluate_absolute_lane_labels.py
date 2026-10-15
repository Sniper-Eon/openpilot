#!/usr/bin/env python3
"""Score an absolute-lane decision report against independent human labels.

A system that never answers is useless but safe, while a single confident wrong
index is worse than an unknown, so coverage and false positives are reported
separately and never averaged into one number.

An index-only match is not an answer: 2 of 4 when the road has 3 lanes is wrong
about the road, so it is not counted as correct and it blocks ``wireable``. A
labelled frame with no prediction record is not covered, and a frame the
annotator could not read is counted as unverifiable rather than credited.

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
  """Score a report against labels, counting the ways a report can flatter itself.

  An index-only match is not an answer: reporting lane 2 of 4 when the road has 3
  is wrong about the road. A labelled frame with no prediction record is not a
  covered frame. A frame the annotator could not read is not a success for the
  system. Each of those is counted separately, and ``wireable`` requires all of
  them to be clean, because a single confident wrong index is worse than unknown.
  """
  if report.get("schema") != REPORT_SCHEMA:
    raise ValueError("unsupported report schema")
  if ground_truth.get("schema") != GROUND_TRUTH_SCHEMA:
    raise ValueError("unsupported ground-truth schema")
  if ground_truth.get("segment") != report.get("segment"):
    raise ValueError("ground-truth segment does not match report")

  labels = ground_truth.get("labels", [])
  if not labels:
    raise ValueError("no labels: nothing was evaluated")
  records = report.get("records", [])
  if len({label["frame_index"] for label in labels}) != len(labels):
    raise ValueError("duplicate frame_index in ground truth")
  if len({record["frame_index"] for record in records}) != len(records):
    raise ValueError("duplicate frame_index in report")
  predictions = {record["frame_index"]: record for record in records}

  labeled = unverifiable = no_prediction = known = correct = 0
  index_correct = count_correct = false_positives = missed = count_mismatches = 0
  unknown_reasons: Counter[str] = Counter()
  false_positive_pairs: dict[int, Counter[int]] = defaultdict(Counter)

  for label in labels:
    frame_index = label["frame_index"]
    truth_index = label.get("lane_index")
    truth_count = label.get("lane_count")
    predicted = predictions.get(frame_index)

    if truth_index is None:
      # The annotator could not read this frame, so the system cannot be
      # credited or charged for it.
      unverifiable += 1
      continue

    labeled += 1
    if predicted is None:
      no_prediction += 1
      missed += 1
      unknown_reasons["noPredictionRecord"] += 1
      continue

    predicted_valid = bool(predicted.get("valid"))
    predicted_index = predicted.get("lane_index") if predicted_valid else None
    if not predicted_valid:
      unknown_reasons[str(predicted.get("reason", "unknown"))] += 1
      missed += 1
      continue

    known += 1
    index_ok = predicted_index == truth_index
    count_ok = truth_count is None or predicted.get("lane_count") == truth_count
    index_correct += index_ok
    count_correct += count_ok
    if not count_ok:
      count_mismatches += 1
    if index_ok and count_ok:
      correct += 1
    if not index_ok:
      false_positives += 1
      if predicted_index is not None:
        false_positive_pairs[truth_index][predicted_index] += 1

  return {
    "labeled": labeled,
    "unverifiable": unverifiable,
    "no_prediction": no_prediction,
    "known": known,
    "correct": correct,
    "index_correct": index_correct,
    "count_correct": count_correct,
    "coverage": _rate(known, labeled),
    "unknown_rate": _rate(labeled - known, labeled),
    "selective_accuracy": _rate(correct, known),
    "end_to_end_accuracy": _rate(correct, labeled),
    "false_positives": false_positives,
    "false_positive_rate": _rate(false_positives, known),
    "missed": missed,
    "count_mismatches": count_mismatches,
    # Anything that should stop a number from being wired to a display.
    "wireable": bool(labeled and known == labeled and false_positives == 0
                     and count_mismatches == 0 and no_prediction == 0),
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
                      help="exit 2 on any wrong confirmed index or wrong lane total")
  parser.add_argument("--require-wireable", action="store_true",
                      help="exit 2 unless every label was answered, with no wrong index or count")
  args = parser.parse_args()

  try:
    metrics = evaluate_absolute_labels(json.loads(args.report.read_text()),
                                       json.loads(args.labels.read_text()))
  except ValueError as error:
    print(f"evaluation refused: {error}")
    return 2
  print(json.dumps(metrics, indent=2, sort_keys=True))
  if args.fail_on_false_positive and (metrics["false_positives"] or metrics["count_mismatches"]):
    return 2
  if args.require_wireable and not metrics["wireable"]:
    return 2
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
