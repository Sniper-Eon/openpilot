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


def test_an_index_only_match_on_the_wrong_total_is_not_an_answer():
  """Saying 2 of 4 when the road has 3 lanes is wrong about the road."""
  metrics = evaluate_absolute_labels(
    report([{"frame_index": 0, "valid": True, "lane_index": 2, "lane_count": 4, "reason": "absoluteConfirmed"}]),
    truth([{"frame_index": 0, "lane_index": 2, "lane_count": 3}]),
  )

  assert metrics["correct"] == 0
  assert metrics["index_correct"] == 1 and metrics["count_correct"] == 0
  assert metrics["count_mismatches"] == 1
  assert metrics["wireable"] is False


def test_a_label_with_no_prediction_record_is_not_covered():
  metrics = evaluate_absolute_labels(
    report([{"frame_index": 0, "valid": True, "lane_index": 1, "lane_count": 1, "reason": "absoluteConfirmed"}]),
    truth([{"frame_index": 0, "lane_index": 1, "lane_count": 1},
           {"frame_index": 1, "lane_index": 1, "lane_count": 1}]),
  )

  assert metrics["labeled"] == 2 and metrics["no_prediction"] == 1
  assert metrics["coverage"] == 0.5 and metrics["end_to_end_accuracy"] == 0.5
  assert metrics["unknown_reasons"] == {"noPredictionRecord": 1}
  assert metrics["wireable"] is False


def test_a_frame_the_annotator_could_not_read_is_neither_credit_nor_blame():
  metrics = evaluate_absolute_labels(
    report([{"frame_index": 0, "valid": True, "lane_index": 2, "lane_count": 3, "reason": "absoluteConfirmed"},
            {"frame_index": 1, "valid": True, "lane_index": 1, "lane_count": 3, "reason": "absoluteConfirmed"}]),
    truth([{"frame_index": 0, "lane_index": 2, "lane_count": 3},
           {"frame_index": 1, "lane_index": None, "lane_count": None}]),
  )

  assert metrics["unverifiable"] == 1 and metrics["labeled"] == 1
  assert metrics["false_positives"] == 0 and metrics["correct"] == 1
  assert metrics["wireable"] is True


def test_an_empty_or_duplicated_label_set_is_refused():
  empty = {"schema": "lane-position-ground-truth-v1", "segment": "drive-01", "labels": []}
  duplicate = truth([{"frame_index": 0, "lane_index": 1, "lane_count": 2},
                     {"frame_index": 0, "lane_index": 1, "lane_count": 2}])
  doubled_report = report([{"frame_index": 0, "valid": True, "lane_index": 1, "lane_count": 2,
                            "reason": "absoluteConfirmed"}] * 2)

  with pytest.raises(ValueError):
    evaluate_absolute_labels(report([]), empty)
  with pytest.raises(ValueError):
    evaluate_absolute_labels(report([]), duplicate)
  with pytest.raises(ValueError):
    evaluate_absolute_labels(doubled_report, truth([{"frame_index": 0, "lane_index": 1, "lane_count": 2}]))


def test_a_system_that_never_answers_is_not_wireable_and_not_wrong():
  metrics = evaluate_absolute_labels(
    report([{"frame_index": 0, "valid": False, "lane_index": None, "lane_count": None,
             "reason": "rightBoundaryNotObserved"}]),
    truth([{"frame_index": 0, "lane_index": 2, "lane_count": 3}]),
  )

  assert metrics["known"] == 0 and metrics["false_positives"] == 0 and metrics["missed"] == 1
  assert metrics["coverage"] == 0.0 and metrics["wireable"] is False


def test_schema_and_segment_must_match_exactly():
  good_report = report([{"frame_index": 0, "valid": True, "lane_index": 1, "lane_count": 1, "reason": "absoluteConfirmed"}])
  good_truth = truth([{"frame_index": 0, "lane_index": 1, "lane_count": 1}])

  with pytest.raises(ValueError):
    evaluate_absolute_labels({**good_report, "schema": "other"}, good_truth)
  with pytest.raises(ValueError):
    evaluate_absolute_labels(good_report, {**good_truth, "schema": "other"})
  with pytest.raises(ValueError):
    evaluate_absolute_labels({**good_report, "segment": "other"}, good_truth)
