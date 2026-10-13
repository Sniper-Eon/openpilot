from types import SimpleNamespace

import pytest

from openpilot.sunnypilot.lane_topology.metric_marking import MetricMarkingEvidence
from openpilot.sunnypilot.lane_topology.types import (
  LaneBoundary,
  LaneMarkingType,
  LaneSpace,
  LaneTopology,
  LaneTopologyState,
)
from openpilot.sunnypilot.navassist.lane_publisher import build_lane_topology_message


NOW_NS = 2_000_000_000


def evidence(marking_type, confidence=0.9):
  return MetricMarkingEvidence(marking_type, confidence, 20, 15, 0.75, 4, 3, 1.0, 3.0, 3, 2, 0.9)


def bridge(*, left=LaneMarkingType.dashed, right=LaneMarkingType.solid,
           raw_left=LaneMarkingType.dashed, raw_right=LaneMarkingType.solid,
           state=LaneTopologyState.normal, timestamp_ns=NOW_NS - 50_000_000):
  topology = LaneTopology(
    frame_id=10,
    timestamp_ns=timestamp_ns,
    boundaries=(
      LaneBoundary(1, ((5.0, 1.8), (40.0, 1.8)), left, 0.9),
      LaneBoundary(2, ((5.0, -1.8), (40.0, -1.8)), right, 0.85),
    ),
    spaces=(LaneSpace(1, 2, 3.6, 0.85),),
    marking_count_visible=2,
    boundary_count_visible=2,
    visible_lane_count=1,
    ego_lane_index_from_left=0,
    ego_lane_index_from_right=0,
    lanes_left_of_ego=0,
    lanes_right_of_ego=0,
    state=state,
    confidence=0.85,
  )
  return SimpleNamespace(
    current=topology,
    ego_source_ids=(1, 2),
    marking_evidence=[MetricMarkingEvidence.unknown(), evidence(raw_left), evidence(raw_right)],
    ego_marking_types=lambda: (left, right),
  )


def three_lane_bridge(*, left_far, left_ego, right_ego, right_far, left_ego_source=-1, right_ego_source=-1):
  topology = LaneTopology(
    frame_id=10,
    timestamp_ns=NOW_NS - 50_000_000,
    boundaries=(
      LaneBoundary(10, ((5.0, 5.4), (40.0, 5.4)), LaneMarkingType.solid, 0.9),
      LaneBoundary(1, ((5.0, 1.8), (40.0, 1.8)), LaneMarkingType.solidDashed, 0.9,
                   left_component_marking=left_far, right_component_marking=left_ego,
                   right_component_source_id=left_ego_source),
      LaneBoundary(2, ((5.0, -1.8), (40.0, -1.8)), LaneMarkingType.solidDashed, 0.9,
                   left_component_marking=right_ego, right_component_marking=right_far,
                   left_component_source_id=right_ego_source),
      LaneBoundary(11, ((5.0, -5.4), (40.0, -5.4)), LaneMarkingType.solid, 0.9),
    ),
    spaces=(LaneSpace(10, 1, 3.6, 0.9), LaneSpace(1, 2, 3.6, 0.9), LaneSpace(2, 11, 3.6, 0.9)),
    marking_count_visible=6,
    boundary_count_visible=4,
    visible_lane_count=3,
    ego_lane_index_from_left=1,
    ego_lane_index_from_right=1,
    lanes_left_of_ego=1,
    lanes_right_of_ego=1,
    state=LaneTopologyState.normal,
    confidence=0.9,
  )
  return SimpleNamespace(
    current=topology,
    ego_source_ids=(1, 2),
    marking_evidence=[MetricMarkingEvidence.unknown(), evidence(left_ego), evidence(right_ego),
                      MetricMarkingEvidence.unknown()],
    ego_marking_types=lambda: (LaneMarkingType.solidDashed, LaneMarkingType.solidDashed),
  )


def test_control_validity_requires_fresh_synchronized_known_evidence():
  message = build_lane_topology_message(
    bridge(), now_ns=NOW_NS, image_mono_time=NOW_NS - 100_000_000, image_frame_id=9,
    calibration_valid=True,
  )
  state = message.laneTopologyStateSP
  assert message.valid and state.valid and state.validForControl
  assert state.leftMarking == "dashed"
  assert state.rightMarking == "solid"
  assert state.leftRawMarking == "dashed"
  assert state.rightRawMarking == "solid"
  assert state.leftEvidenceValid
  assert state.rightEvidenceValid
  assert state.imageModelSkewMs == pytest.approx(50.0)
  assert state.leftMarkingConfidence == pytest.approx(0.9)


def test_unknown_current_evidence_blocks_only_that_crossing_direction():
  message = build_lane_topology_message(
    bridge(raw_left=LaneMarkingType.unknown), now_ns=NOW_NS,
    image_mono_time=NOW_NS - 100_000_000, calibration_valid=True,
  )
  assert message.laneTopologyStateSP.validForControl
  assert not message.laneTopologyStateSP.leftEvidenceValid
  assert not message.laneTopologyStateSP.leftCrossingAllowed


def test_mixed_lines_allow_crossing_only_when_ego_side_is_dashed():
  state = build_lane_topology_message(
    three_lane_bridge(
      left_far=LaneMarkingType.solid,
      left_ego=LaneMarkingType.dashed,
      right_ego=LaneMarkingType.solid,
      right_far=LaneMarkingType.dashed,
    ),
    now_ns=NOW_NS,
    image_mono_time=NOW_NS - 100_000_000,
    calibration_valid=True,
  ).laneTopologyStateSP

  assert state.validForControl
  assert state.leftEgoSideMarking == "dashed"
  assert state.leftFarSideMarking == "solid"
  assert state.leftCrossingAllowed
  assert state.rightEgoSideMarking == "solid"
  assert state.rightFarSideMarking == "dashed"
  assert not state.rightCrossingAllowed


def test_crossing_requires_current_raw_evidence_for_the_ego_side_component():
  state = build_lane_topology_message(
    three_lane_bridge(
      left_far=LaneMarkingType.solid,
      left_ego=LaneMarkingType.dashed,
      right_ego=LaneMarkingType.solid,
      right_far=LaneMarkingType.dashed,
      left_ego_source=3,
    ),
    now_ns=NOW_NS,
    image_mono_time=NOW_NS - 100_000_000,
    calibration_valid=True,
  ).laneTopologyStateSP

  assert state.validForControl
  assert not state.leftEvidenceValid
  assert state.rightEvidenceValid
  assert not state.leftCrossingAllowed


def test_right_dashed_crossing_is_not_blocked_by_unknown_left_boundary():
  state = build_lane_topology_message(
    three_lane_bridge(
      left_far=LaneMarkingType.solid,
      left_ego=LaneMarkingType.unknown,
      right_ego=LaneMarkingType.dashed,
      right_far=LaneMarkingType.solid,
    ),
    now_ns=NOW_NS,
    image_mono_time=NOW_NS - 100_000_000,
    calibration_valid=True,
  ).laneTopologyStateSP

  assert state.validForControl
  assert not state.leftCrossingAllowed
  assert state.rightCrossingAllowed


def test_fresh_but_time_mismatched_image_is_not_control_valid():
  state = build_lane_topology_message(
    bridge(timestamp_ns=NOW_NS - 20_000_000),
    now_ns=NOW_NS,
    image_mono_time=NOW_NS - 300_000_000,
    calibration_valid=True,
  ).laneTopologyStateSP

  assert state.stale
  assert not state.validForControl


def test_stale_ambiguous_source_change_or_bad_calibration_fail_closed():
  stale = build_lane_topology_message(
    bridge(), now_ns=NOW_NS, image_mono_time=NOW_NS - 500_000_001, calibration_valid=True,
  ).laneTopologyStateSP
  assert stale.stale and not stale.validForControl

  ambiguous = build_lane_topology_message(
    bridge(state=LaneTopologyState.ambiguous), now_ns=NOW_NS,
    image_mono_time=NOW_NS - 1, calibration_valid=True,
  ).laneTopologyStateSP
  assert ambiguous.ambiguous and not ambiguous.validForControl

  changed = build_lane_topology_message(
    bridge(), now_ns=NOW_NS, image_mono_time=NOW_NS - 1,
    calibration_valid=True, source_pair_changed=True,
  ).laneTopologyStateSP
  assert changed.sourcePairChanged and not changed.validForControl

  uncalibrated = build_lane_topology_message(
    bridge(), now_ns=NOW_NS, image_mono_time=NOW_NS - 1, calibration_valid=False,
  ).laneTopologyStateSP
  assert not uncalibrated.validForControl


def test_no_topology_publishes_invalid_stale_message():
  empty = SimpleNamespace(current=None)
  message = build_lane_topology_message(empty, now_ns=NOW_NS)
  assert not message.valid
  assert message.laneTopologyStateSP.stale
  assert not message.laneTopologyStateSP.validForControl
