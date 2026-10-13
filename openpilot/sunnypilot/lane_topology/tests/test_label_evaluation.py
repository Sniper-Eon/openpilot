from tools.evaluate_lane_marking_labels import evaluate_labels


def test_ground_truth_evaluation_separates_coverage_from_accuracy_and_solid_as_dashed():
  report = {
    "segment": "route--1",
    "records": [
      {"frame_index": 10, "stable_markings": ["unknown", "solid", "dashed", "unknown"]},
      {"frame_index": 20, "stable_markings": ["unknown", "dashed", "unknown", "unknown"]},
    ],
  }
  labels = {
    "schema": "lane-marking-ground-truth-v1",
    "segment": "route--1",
    "labels": [
      {"frame_index": 10, "source_id": 1, "expected": "solid", "condition": "clear"},
      {"frame_index": 10, "source_id": 2, "expected": "dashed", "condition": "blurred"},
      {"frame_index": 20, "source_id": 1, "expected": "solid", "condition": "blurred"},
      {"frame_index": 20, "source_id": 2, "expected": "dashed", "condition": "blurred"},
    ],
  }

  result = evaluate_labels(report, labels)

  assert result["labeled"] == 4
  assert result["known"] == 3
  assert result["correct"] == 2
  assert result["coverage"] == 0.75
  assert result["selective_accuracy"] == 2 / 3
  assert result["end_to_end_accuracy"] == 0.5
  assert result["solid_as_dashed"] == 1
  assert result["by_condition"]["blurred"]["solid_as_dashed"] == 1
