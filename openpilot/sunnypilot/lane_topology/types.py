from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
import math


class LaneMarkingType(IntEnum):
  unknown = 0
  solid = 1
  dashed = 2
  doubleSolid = 3
  doubleDashed = 4
  solidDashed = 5
  roadEdge = 6

  @property
  def physical_marking_count(self) -> int:
    return 2 if self in (LaneMarkingType.doubleSolid, LaneMarkingType.doubleDashed, LaneMarkingType.solidDashed) else 1


class LaneTopologyState(IntEnum):
  normal = 0
  mergingLeft = 1
  mergingRight = 2
  splittingLeft = 3
  splittingRight = 4
  ambiguous = 5
  stale = 6


@dataclass(frozen=True)
class LaneBoundaryObservation:
  """One model-observed physical lane marking in vehicle coordinates.

  ``x`` is forward and ``y`` is left-positive, both in metres. Points need not
  arrive sorted; geometry canonicalizes them before interpolation.
  """

  source_id: int
  points: tuple[tuple[float, float], ...]
  marking_type: LaneMarkingType = LaneMarkingType.unknown
  confidence: float = 0.0
  visible: bool = True

  def __post_init__(self) -> None:
    if len(self.points) < 2:
      raise ValueError("a lane boundary needs at least two points")
    if not 0.0 <= self.confidence <= 1.0:
      raise ValueError("confidence must be within [0, 1]")
    if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in self.points):
      raise ValueError("lane boundary points must be finite")


@dataclass(frozen=True)
class LaneBoundary:
  track_id: int
  points: tuple[tuple[float, float], ...]
  marking_type: LaneMarkingType
  confidence: float
  visible: bool = True
  missed_frames: int = 0
  left_component_marking: LaneMarkingType | None = None
  right_component_marking: LaneMarkingType | None = None
  left_component_source_id: int = -1
  right_component_source_id: int = -1

  def __post_init__(self) -> None:
    if self.left_component_marking is None:
      object.__setattr__(self, "left_component_marking", self.marking_type)
    if self.right_component_marking is None:
      object.__setattr__(self, "right_component_marking", self.marking_type)

  def with_track(self, track_id: int) -> LaneBoundary:
    return replace(self, track_id=track_id)


@dataclass(frozen=True)
class LaneSpace:
  left_track_id: int
  right_track_id: int
  width_m: float
  confidence: float


@dataclass(frozen=True)
class LaneTopology:
  frame_id: int
  timestamp_ns: int
  boundaries: tuple[LaneBoundary, ...]
  spaces: tuple[LaneSpace, ...]
  marking_count_visible: int
  boundary_count_visible: int
  visible_lane_count: int
  ego_lane_index_from_left: int
  ego_lane_index_from_right: int
  lanes_left_of_ego: int
  lanes_right_of_ego: int
  state: LaneTopologyState
  confidence: float
  stale: bool = False
  model_latency_ms: float = 0.0

  @classmethod
  def empty(cls, frame_id: int, timestamp_ns: int, *, stale: bool = False) -> LaneTopology:
    return cls(
      frame_id=frame_id,
      timestamp_ns=timestamp_ns,
      boundaries=(),
      spaces=(),
      marking_count_visible=0,
      boundary_count_visible=0,
      visible_lane_count=0,
      ego_lane_index_from_left=-1,
      ego_lane_index_from_right=-1,
      lanes_left_of_ego=0,
      lanes_right_of_ego=0,
      state=LaneTopologyState.stale if stale else LaneTopologyState.ambiguous,
      confidence=0.0,
      stale=stale,
    )
