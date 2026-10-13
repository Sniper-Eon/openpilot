from openpilot.sunnypilot.lane_topology.tracker import LaneTopologyTracker
from openpilot.sunnypilot.lane_topology.types import LaneBoundaryObservation, LaneMarkingType


def line(source_id: int, y: float, marking_type: LaneMarkingType = LaneMarkingType.dashed,
         confidence: float = 0.9) -> LaneBoundaryObservation:
  return LaneBoundaryObservation(source_id, ((5.0, y), (10.0, y), (40.0, y)), marking_type, confidence)


def test_track_ids_survive_model_source_id_changes_and_reordering():
  tracker = LaneTopologyTracker()
  first = tracker.update((line(10, 1.8), line(11, -1.8)), frame_id=1, timestamp_ns=1)
  second = tracker.update((line(99, -1.75), line(98, 1.85)), frame_id=2, timestamp_ns=2)
  assert [boundary.track_id for boundary in first.boundaries] == [1, 2]
  assert [boundary.track_id for boundary in second.boundaries] == [1, 2]


def test_marking_type_uses_temporal_evidence_instead_of_one_frame_flip():
  tracker = LaneTopologyTracker()
  tracker.update((line(1, 1.8, LaneMarkingType.solid, 0.9), line(2, -1.8)), frame_id=1, timestamp_ns=1)
  second = tracker.update((line(7, 1.8, LaneMarkingType.dashed, 0.2), line(8, -1.8)), frame_id=2, timestamp_ns=2)
  assert second.boundaries[0].marking_type == LaneMarkingType.solid


def test_unknown_image_evidence_does_not_erase_a_known_marking_type():
  tracker = LaneTopologyTracker()
  tracker.update((line(1, 1.8, LaneMarkingType.solid, 0.9), line(2, -1.8)), frame_id=1, timestamp_ns=1)
  second = tracker.update((line(1, 1.8, LaneMarkingType.unknown, 0.9), line(2, -1.8)), frame_id=2, timestamp_ns=2)
  assert second.boundaries[0].marking_type == LaneMarkingType.solid


def test_expired_track_gets_a_new_stable_id():
  tracker = LaneTopologyTracker(max_missed_frames=1)
  first = tracker.update((line(1, 1.8), line(2, -1.8)), frame_id=1, timestamp_ns=1)
  tracker.update((), frame_id=2, timestamp_ns=2)
  tracker.update((), frame_id=3, timestamp_ns=3)
  fourth = tracker.update((line(9, 1.8), line(10, -1.8)), frame_id=4, timestamp_ns=4)
  assert first.boundaries[0].track_id == 1
  assert fourth.boundaries[0].track_id > 2
