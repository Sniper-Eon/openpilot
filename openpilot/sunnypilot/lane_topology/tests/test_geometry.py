import pytest

from openpilot.sunnypilot.lane_topology.geometry import analyze_lane_topology, interpolate_y
from openpilot.sunnypilot.lane_topology.types import LaneBoundaryObservation, LaneMarkingType, LaneTopologyState


def line(source_id: int, y: float, marking_type: LaneMarkingType = LaneMarkingType.dashed,
         *, far_y: float | None = None, confidence: float = 0.9) -> LaneBoundaryObservation:
  return LaneBoundaryObservation(source_id, ((5.0, y), (10.0, y), (40.0, y if far_y is None else far_y)),
                                 marking_type, confidence)


def test_four_boundaries_form_three_visible_lanes_and_center_ego_lane():
  result = analyze_lane_topology((line(1, 5.4), line(2, 1.8), line(3, -1.8), line(4, -5.4)),
                                 frame_id=12, timestamp_ns=34)
  assert result.marking_count_visible == 4
  assert result.boundary_count_visible == 4
  assert result.visible_lane_count == 3
  assert result.ego_lane_index_from_left == 1
  assert result.ego_lane_index_from_right == 1
  assert result.lanes_left_of_ego == 1
  assert result.lanes_right_of_ego == 1
  assert result.state == LaneTopologyState.normal


def test_two_close_solid_markings_become_one_double_solid_boundary():
  result = analyze_lane_topology((
    line(1, 1.92, LaneMarkingType.solid),
    line(2, 1.68, LaneMarkingType.solid),
    line(3, -1.8, LaneMarkingType.dashed),
  ), frame_id=1, timestamp_ns=2)
  assert result.boundary_count_visible == 2
  assert result.marking_count_visible == 3
  assert result.boundaries[0].marking_type == LaneMarkingType.doubleSolid
  assert interpolate_y(result.boundaries[0].points, 10.0) == pytest.approx(1.8)
  assert result.visible_lane_count == 1
  assert result.ego_lane_index_from_left == 0


@pytest.mark.parametrize(("left_type", "right_type"), [
  (LaneMarkingType.solid, LaneMarkingType.dashed),
  (LaneMarkingType.dashed, LaneMarkingType.solid),
])
def test_mixed_double_line_preserves_vehicle_side_order(left_type, right_type):
  result = analyze_lane_topology((
    line(1, 1.92, left_type),
    line(2, 1.68, right_type),
    line(3, -1.8, LaneMarkingType.dashed),
  ), frame_id=1, timestamp_ns=2)

  boundary = result.boundaries[0]
  assert boundary.marking_type == LaneMarkingType.solidDashed
  assert boundary.left_component_marking == left_type
  assert boundary.right_component_marking == right_type


def test_implausible_boundary_gap_is_not_counted_as_a_lane():
  result = analyze_lane_topology((line(1, 1.0), line(2, -1.0), line(3, -8.0)), frame_id=1, timestamp_ns=2)
  assert result.visible_lane_count == 0
  assert result.ego_lane_index_from_left == -1
  assert result.state == LaneTopologyState.ambiguous


def test_converging_left_boundaries_report_merge():
  result = analyze_lane_topology((
    line(1, 5.2, far_y=2.1),
    line(2, 1.8, far_y=1.8),
    line(3, -1.8),
  ), frame_id=1, timestamp_ns=2)
  assert result.state == LaneTopologyState.mergingLeft


def test_points_are_interpolated_after_sorting():
  points = ((40.0, 2.0), (5.0, 1.0), (10.0, 1.5))
  assert interpolate_y(points, 7.5) == 1.25
  assert interpolate_y(points, 2.0) is None
