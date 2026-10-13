from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from openpilot.sunnypilot.lane_topology.types import LaneBoundaryObservation


@dataclass(frozen=True)
class LaneTopologyFrame:
  """Frame context passed through the Lane Topology model seam.

  ``payload`` stays opaque so the production adapter can receive a VisionBuf
  while replay tests use fixture identifiers without importing camera or GPU
  modules into the topology implementation.
  """

  frame_id: int
  timestamp_ns: int
  payload: object
  calibration: object | None = None
  primary_latency_ms: float = 0.0
  dropped_frames: int = 0
  prepare_only: bool = False
  calibration_valid: bool = True


class LaneTopologyModelAdapter(Protocol):
  def infer(self, frame: LaneTopologyFrame) -> tuple[LaneBoundaryObservation, ...]: ...
  def close(self) -> None: ...


class DisabledLaneTopologyAdapter:
  def infer(self, frame: LaneTopologyFrame) -> tuple[LaneBoundaryObservation, ...]:
    del frame
    return ()

  def close(self) -> None:
    pass


class CallableLaneTopologyAdapter:
  """Adapter for an in-process callable that already shares the GPU owner."""

  def __init__(self, infer: Callable[[LaneTopologyFrame], tuple[LaneBoundaryObservation, ...]],
               close: Callable[[], None] | None = None):
    self._infer = infer
    self._close = close

  def infer(self, frame: LaneTopologyFrame) -> tuple[LaneBoundaryObservation, ...]:
    return tuple(self._infer(frame))

  def close(self) -> None:
    if self._close is not None:
      self._close()


class ReplayLaneTopologyAdapter:
  """Deterministic adapter for route fixtures and offline timing tests."""

  def __init__(self, frames: Mapping[int, tuple[LaneBoundaryObservation, ...]]):
    self._frames = dict(frames)

  def infer(self, frame: LaneTopologyFrame) -> tuple[LaneBoundaryObservation, ...]:
    return self._frames.get(frame.frame_id, ())

  def close(self) -> None:
    pass
