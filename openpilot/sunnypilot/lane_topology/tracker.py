from __future__ import annotations

from dataclasses import dataclass, field, replace

from openpilot.sunnypilot.lane_topology.geometry import SAMPLE_X_M, analyze_lane_topology, canonical_points, interpolate_y
from openpilot.sunnypilot.lane_topology.types import LaneBoundary, LaneBoundaryObservation, LaneMarkingType, LaneTopology


@dataclass
class _Track:
  track_id: int
  boundary: LaneBoundary
  missed_frames: int = 0
  type_scores: dict[LaneMarkingType, float] = field(default_factory=dict)

  def update_type(self, marking_type: LaneMarkingType, confidence: float) -> LaneMarkingType:
    self.type_scores = {key: score * 0.8 for key, score in self.type_scores.items() if score * 0.8 >= 0.05}
    if marking_type == LaneMarkingType.unknown:
      return max(self.type_scores, key=self.type_scores.get) if self.type_scores else LaneMarkingType.unknown
    self.type_scores[marking_type] = self.type_scores.get(marking_type, 0.0) + confidence
    return max(self.type_scores, key=self.type_scores.get)


class LaneTopologyTracker:
  def __init__(self, *, association_distance_m: float = 0.9, max_missed_frames: int = 3, smooth_marking_types: bool = True):
    self.association_distance_m = association_distance_m
    self.max_missed_frames = max_missed_frames
    self.smooth_marking_types = smooth_marking_types
    self._tracks: dict[int, _Track] = {}
    self._next_track_id = 1

  def reset(self) -> None:
    self._tracks.clear()
    self._next_track_id = 1

  def _associate(self, observations: tuple[LaneBoundaryObservation, ...]) -> dict[int, int]:
    candidates: list[tuple[float, int, int]] = []
    for observation_index, observation in enumerate(observations):
      observation_y = interpolate_y(canonical_points(observation.points), SAMPLE_X_M)
      if observation_y is None:
        continue
      for track_id, track in self._tracks.items():
        track_y = interpolate_y(track.boundary.points, SAMPLE_X_M)
        if track_y is not None and (distance := abs(observation_y - track_y)) <= self.association_distance_m:
          candidates.append((distance, observation_index, track_id))

    matches: dict[int, int] = {}
    used_tracks: set[int] = set()
    for _, observation_index, track_id in sorted(candidates):
      if observation_index not in matches and track_id not in used_tracks:
        matches[observation_index] = track_id
        used_tracks.add(track_id)
    return matches

  def update(self, observations: tuple[LaneBoundaryObservation, ...], *, frame_id: int, timestamp_ns: int,
             model_latency_ms: float = 0.0) -> LaneTopology:
    visible = tuple(observation for observation in observations if observation.visible)
    matches = self._associate(visible)
    seen_tracks: set[int] = set()
    tracked_boundaries: list[LaneBoundary] = []

    for index, observation in enumerate(visible):
      track_id = matches.get(index)
      if track_id is None:
        track_id = self._next_track_id
        self._next_track_id += 1
        boundary = LaneBoundary(track_id, canonical_points(observation.points), observation.marking_type,
                                observation.confidence, visible=True,
                                left_component_source_id=observation.source_id,
                                right_component_source_id=observation.source_id)
        track = self._tracks[track_id] = _Track(track_id, boundary)
      else:
        track = self._tracks[track_id]
      stable_type = (track.update_type(observation.marking_type, observation.confidence)
                     if self.smooth_marking_types else observation.marking_type)
      track.boundary = LaneBoundary(track_id, canonical_points(observation.points), stable_type,
                                    observation.confidence, visible=True,
                                    left_component_source_id=observation.source_id,
                                    right_component_source_id=observation.source_id)
      track.missed_frames = 0
      seen_tracks.add(track_id)
      tracked_boundaries.append(track.boundary)

    for track_id, track in tuple(self._tracks.items()):
      if track_id in seen_tracks:
        continue
      track.missed_frames += 1
      if track.missed_frames > self.max_missed_frames:
        del self._tracks[track_id]
      else:
        track.boundary = replace(track.boundary, visible=False, missed_frames=track.missed_frames,
                                 confidence=track.boundary.confidence * 0.7)

    return analyze_lane_topology(tuple(tracked_boundaries), frame_id=frame_id, timestamp_ns=timestamp_ns,
                                 model_latency_ms=model_latency_ms)
