import pytest

from tools.evaluate_absolute_lane_labels import evaluate_absolute_labels


def report(records):
  return {"schema": "absolute-lane-report-v1", "segment": "drive-01", "records": records}


def truth(labels):
  return {"schema": "lane-position-ground-truth-v1", "segment": "drive-01", "labels": labels}


def test_coverage_and_false_positives_are_never_averaged_together():
  metrics = evaluate_absolute_labels(
    report([
      {"frame_index": 0, "valid": True, "lane_index": 2, "lane_count": 3, "reason": "absoluteConfirmed"},
      {"frame_index": 1, "valid": True, "lane_index": 1, "lane_count": 3, "reason": "absoluteConfirmed"},
      {"frame_index": 2, "valid": False, "lane_index": None, "lane_count": None, "reason": "stabilizing"},
      {"frame_index": 3, "valid": False, "lane_index": None, "lane_count": None, "reason": "implausibleLaneWidth"},
    ]),
    truth([
      {"frame_index": 0, "lane_index": 2, "lane_count": 3},
      {"frame_index": 1, "lane_index": 2, "lane_count": 3},
      {"frame_index": 2, "lane_index": 3, "lane_count": 3},
      {"frame_index": 3, "lane_index": 3, "lane_count": 3},
    ]),
  )

  assert metrics["labeled"] == 4 and metrics["known"] == 2 and metrics["correct"] == 1
  assert metrics["coverage"] == 0.5 and metrics["unknown_rate"] == 0.5
  assert metrics["selective_accuracy"] == 0.5
  assert metrics["end_to_end_accuracy"] == 0.25
  assert metrics["false_positives"] == 1 and metrics["false_positive_rate"] == 0.5
  assert metrics["missed"] == 2
  assert metrics["false_positive_pairs"] == {"2": {"1": 1}}
  assert metrics["unknown_reasons"] == {"implausibleLaneWidth": 1, "stabilizing": 1}


def test_a_silent_system_shows_full_unknown_and_zero_false_positives():
  metrics = evaluate_absolute_labels(
    report([{"frame_index": 0, "valid": False, "lane_index": None, "lane_count": None, "reason": "edgeMarkingNotConfirmed"}]),
    truth([{"frame_index": 0, "lane_index": 1, "lane_count": 1}]),
  )

  assert metrics["coverage"] == 0.0 and metrics["selective_accuracy"] == 0.0
  assert metrics["false_positives"] == 0 and metrics["missed"] == 1
  assert metrics["unknown_reasons"] == {"edgeMarkingNotConfirmed": 1}


def test_a_total_that_disagrees_with_the_label_is_counted():
  metrics = evaluate_absolute_labels(
    report([{"frame_index": 0, "valid": True, "lane_index": 2, "lane_count": 4, "reason": "absoluteConfirmed"}]),
    truth([{"frame_index": 0, "lane_index": 2, "lane_count": 3}]),
  )

  assert metrics["correct"] == 1 and metrics["count_mismatches"] == 1


def test_frames_without_a_prediction_are_not_scored():
  metrics = evaluate_absolute_labels(
    report([{"frame_index": 0, "valid": True, "lane_index": 1, "lane_count": 1, "reason": "absoluteConfirmed"}]),
    truth([{"frame_index": 0, "lane_index": 1, "lane_count": 1},
           {"frame_index": 1, "lane_index": 1, "lane_count": 1}]),
  )

  assert metrics["labeled"] == 1 and metrics["end_to_end_accuracy"] == 1.0


def test_schema_and_segment_must_match_exactly():
  good_report = report([{"frame_index": 0, "valid": True, "lane_index": 1, "lane_count": 1, "reason": "absoluteConfirmed"}])
  good_truth = truth([{"frame_index": 0, "lane_index": 1, "lane_count": 1}])

  with pytest.raises(ValueError):
    evaluate_absolute_labels({**good_report, "schema": "other"}, good_truth)
  with pytest.raises(ValueError):
    evaluate_absolute_labels(good_report, {**good_truth, "schema": "other"})
  with pytest.raises(ValueError):
    evaluate_absolute_labels({**good_report, "segment": "other"}, good_truth)
