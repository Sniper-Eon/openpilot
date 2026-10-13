from __future__ import annotations

from openpilot.cereal import messaging
from openpilot.sunnypilot.lane_topology.types import LaneMarkingType, LaneTopologyState


MODEL_MAX_AGE_NS = 150_000_000
MARKING_MAX_AGE_NS = 500_000_000
MODEL_IMAGE_MAX_SKEW_NS = 100_000_000

MARKING_TO_CEREAL = {
  LaneMarkingType.unknown: "unknown",
  LaneMarkingType.solid: "solid",
  LaneMarkingType.dashed: "dashed",
  LaneMarkingType.doubleSolid: "doubleSolid",
  LaneMarkingType.doubleDashed: "doubleDashed",
  LaneMarkingType.solidDashed: "solidDashed",
  LaneMarkingType.roadEdge: "roadEdge",
}
TOPOLOGY_TO_CEREAL = {
  LaneTopologyState.normal: "normal",
  LaneTopologyState.mergingLeft: "mergingLeft",
  LaneTopologyState.mergingRight: "mergingRight",
  LaneTopologyState.splittingLeft: "splittingLeft",
  LaneTopologyState.splittingRight: "splittingRight",
  LaneTopologyState.ambiguous: "ambiguous",
  LaneTopologyState.stale: "stale",
}
CROSSABLE_EGO_MARKINGS = {LaneMarkingType.dashed, LaneMarkingType.doubleDashed}


def raw_marking_matches(bridge, source_id: int, expected: LaneMarkingType) -> bool:
  return bool(
    0 <= source_id < len(bridge.marking_evidence)
    and bridge.marking_evidence[source_id].marking_type == expected
    and expected != LaneMarkingType.unknown
  )


def build_lane_topology_message(bridge, *, now_ns: int, image_mono_time: int = 0, image_frame_id: int = 0,
                                image_model_mono_time: int | None = None,
                                calibration_valid: bool = False, source_pair_changed: bool = False):
  message = messaging.new_message("laneTopologyStateSP")
  state = message.laneTopologyStateSP
  state.publishMonoTime = now_ns
  topology = bridge.current
  if topology is None:
    message.valid = False
    state.stale = True
    state.ambiguous = True
    state.topologyState = "stale"
    return message

  model_age_ns = now_ns - topology.timestamp_ns
  model_fresh = 0 <= model_age_ns <= MODEL_MAX_AGE_NS
  image_age_ns = now_ns - image_mono_time if image_mono_time else MARKING_MAX_AGE_NS + 1
  image_fresh = 0 <= image_age_ns <= MARKING_MAX_AGE_NS
  evidence_model_mono_time = topology.timestamp_ns if image_model_mono_time is None else image_model_mono_time
  image_synchronized = bool(
    image_mono_time and evidence_model_mono_time and
    abs(int(image_mono_time) - int(evidence_model_mono_time)) <= MODEL_IMAGE_MAX_SKEW_NS
  )
  state.imageModelSkewMs = (
    abs(int(image_mono_time) - int(evidence_model_mono_time)) / 1e6
    if image_mono_time and evidence_model_mono_time else 0.0
  )
  state.modelMonoTime = topology.timestamp_ns
  state.imageMonoTime = image_mono_time
  state.frameId = topology.frame_id
  state.imageFrameId = image_frame_id
  state.calibrationValid = calibration_valid
  state.topologyState = TOPOLOGY_TO_CEREAL[topology.state]
  state.visibleLaneCount = max(0, topology.visible_lane_count)
  state.egoLaneIndexFromLeft = topology.ego_lane_index_from_left
  state.egoLaneIndexFromRight = topology.ego_lane_index_from_right
  state.leftNeighborExists = topology.lanes_left_of_ego > 0
  state.rightNeighborExists = topology.lanes_right_of_ego > 0
  state.sourcePairChanged = source_pair_changed

  marking_types = bridge.ego_marking_types()
  left_type, right_type = marking_types or (LaneMarkingType.unknown, LaneMarkingType.unknown)
  state.leftMarking = MARKING_TO_CEREAL[left_type]
  state.rightMarking = MARKING_TO_CEREAL[right_type]
  state.leftEvidenceAgeMs = max(0.0, image_age_ns / 1e6)
  state.rightEvidenceAgeMs = max(0.0, image_age_ns / 1e6)

  if bridge.ego_source_ids is not None:
    left_source, right_source = bridge.ego_source_ids
    left_evidence = bridge.marking_evidence[left_source]
    right_evidence = bridge.marking_evidence[right_source]
    state.leftMarkingConfidence = left_evidence.confidence
    state.rightMarkingConfidence = right_evidence.confidence

  left_ego = left_far = right_ego = right_far = LaneMarkingType.unknown
  left_raw = right_raw = LaneMarkingType.unknown
  left_ego_raw_known = right_ego_raw_known = False
  if topology.ego_lane_index_from_left >= 0:
    ego_space = topology.spaces[topology.ego_lane_index_from_left]
    by_track = {boundary.track_id: boundary for boundary in topology.boundaries}
    left_boundary = by_track.get(ego_space.left_track_id)
    right_boundary = by_track.get(ego_space.right_track_id)
    if left_boundary is not None:
      state.leftBoundaryConfidence = left_boundary.confidence
    if right_boundary is not None:
      state.rightBoundaryConfidence = right_boundary.confidence
    left_ego = left_boundary.right_component_marking if left_boundary is not None else LaneMarkingType.unknown
    left_far = left_boundary.left_component_marking if left_boundary is not None else LaneMarkingType.unknown
    right_ego = right_boundary.left_component_marking if right_boundary is not None else LaneMarkingType.unknown
    right_far = right_boundary.right_component_marking if right_boundary is not None else LaneMarkingType.unknown
    left_fallback_source = bridge.ego_source_ids[0] if bridge.ego_source_ids is not None else -1
    right_fallback_source = bridge.ego_source_ids[1] if bridge.ego_source_ids is not None else -1
    left_ego_source = (left_boundary.right_component_source_id if left_boundary is not None and
                       left_boundary.right_component_source_id >= 0 else left_fallback_source)
    right_ego_source = (right_boundary.left_component_source_id if right_boundary is not None and
                        right_boundary.left_component_source_id >= 0 else right_fallback_source)
    left_ego_raw_known = raw_marking_matches(bridge, left_ego_source, left_ego or LaneMarkingType.unknown)
    right_ego_raw_known = raw_marking_matches(bridge, right_ego_source, right_ego or LaneMarkingType.unknown)
    if 0 <= left_ego_source < len(bridge.marking_evidence):
      left_raw = bridge.marking_evidence[left_ego_source].marking_type
    if 0 <= right_ego_source < len(bridge.marking_evidence):
      right_raw = bridge.marking_evidence[right_ego_source].marking_type
    state.leftEgoSideMarking = MARKING_TO_CEREAL[left_ego or LaneMarkingType.unknown]
    state.leftFarSideMarking = MARKING_TO_CEREAL[left_far or LaneMarkingType.unknown]
    state.rightEgoSideMarking = MARKING_TO_CEREAL[right_ego or LaneMarkingType.unknown]
    state.rightFarSideMarking = MARKING_TO_CEREAL[right_far or LaneMarkingType.unknown]
  state.leftRawMarking = MARKING_TO_CEREAL[left_raw]
  state.rightRawMarking = MARKING_TO_CEREAL[right_raw]

  ambiguous = topology.state != LaneTopologyState.normal or topology.ego_lane_index_from_left < 0
  stale = bool(topology.stale or not model_fresh or not image_fresh or not image_synchronized)
  state.ambiguous = ambiguous
  state.stale = stale
  state.validForControl = bool(
    calibration_valid and not stale and not ambiguous and not source_pair_changed
  )
  state.leftEvidenceValid = bool(state.validForControl and left_ego != LaneMarkingType.unknown and left_ego_raw_known)
  state.rightEvidenceValid = bool(state.validForControl and right_ego != LaneMarkingType.unknown and right_ego_raw_known)
  state.leftCrossingAllowed = bool(
    state.leftEvidenceValid and state.leftNeighborExists and left_ego in CROSSABLE_EGO_MARKINGS
  )
  state.rightCrossingAllowed = bool(
    state.rightEvidenceValid and state.rightNeighborExists and right_ego in CROSSABLE_EGO_MARKINGS
  )
  state.valid = bool(model_fresh and not topology.stale)
  message.valid = True
  return message
