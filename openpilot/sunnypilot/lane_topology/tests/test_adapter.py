from openpilot.sunnypilot.lane_topology.adapter import (
  CallableLaneTopologyAdapter,
  DisabledLaneTopologyAdapter,
  LaneTopologyFrame,
  ReplayLaneTopologyAdapter,
)
from openpilot.sunnypilot.lane_topology.types import LaneBoundaryObservation


def line(source_id: int, y: float) -> LaneBoundaryObservation:
  return LaneBoundaryObservation(source_id, ((5.0, y), (10.0, y)), confidence=0.9)


def test_replay_adapter_is_deterministic_and_missing_frames_are_empty():
  adapter = ReplayLaneTopologyAdapter({7: (line(1, 1.8),)})
  assert len(adapter.infer(LaneTopologyFrame(7, 70, "frame"))) == 1
  assert adapter.infer(LaneTopologyFrame(8, 80, "frame")) == ()


def test_callable_adapter_receives_opaque_payload_without_gpu_imports():
  seen: list[object] = []
  adapter = CallableLaneTopologyAdapter(lambda frame: (seen.append(frame.payload) or (line(1, 1.8),)))
  assert len(adapter.infer(LaneTopologyFrame(1, 2, {"vision": 3}))) == 1
  assert seen == [{"vision": 3}]


def test_disabled_adapter_has_no_output():
  assert DisabledLaneTopologyAdapter().infer(LaneTopologyFrame(1, 2, object())) == ()
