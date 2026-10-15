from types import SimpleNamespace as NS

import pytest

from openpilot.sunnypilot.lane_topology.primary_edges import primary_edge_candidate


def curve(y):
  return NS(x=(0., 10., 30.), y=(y,) * 3)


def model(index=2, count=3, width=3.6):
  return NS(laneLines=[curve(y * width) for y in (-1.5, -.5, .5, 1.5)],
            roadEdges=[curve(-(index - .5) * width), curve((count - index + .5) * width)],
            laneLineProbs=[.9] * 4, roadEdgeStds=[.1, .1])


@pytest.mark.parametrize('index,count', [(1, 1), (1, 3), (2, 3), (3, 3), (3, 5)])
def test_actual_width_and_device_sign_produce_candidate_only(index, count):
  result = primary_edge_candidate(model(index, count))
  assert (result.candidate_index, result.candidate_count) == (index, count)
  assert result.lane_width_m == pytest.approx(3.6)
  assert not result.absolute_confirmed


def test_missing_data_never_becomes_one_of_one():
  result = primary_edge_candidate(NS())
  assert result.candidate_index is None and result.candidate_count is None


@pytest.mark.parametrize('std', [float('nan'), float('inf'), -.1, 1.])
def test_bad_road_edge_uncertainty_is_unknown(std):
  m = model()
  m.roadEdgeStds[0] = std
  assert primary_edge_candidate(m).candidate_index is None


def test_shoulder_fraction_is_not_rounded_into_a_lane():
  m = model()
  m.roadEdges[1] = curve(6.8)
  assert primary_edge_candidate(m).reason == 'nonIntegralRoadWidth'


def test_inverted_and_outside_edges_are_rejected():
  m = model()
  m.roadEdges.reverse()
  assert primary_edge_candidate(m).reason == 'inconsistentEdgeOrder'


def test_weak_ego_lines_do_not_supply_a_width():
  m = model()
  m.laneLineProbs[1] = .1
  assert primary_edge_candidate(m).reason == 'uncertainEgoLines'


def test_fork_geometry_must_agree_along_the_road():
  m = model()
  m.roadEdges[0].y = (-5.4, -5.4, -12.6)
  assert primary_edge_candidate(m).candidate_index is None


def test_malformed_curves_do_not_supply_a_candidate():
  m = model()
  m.laneLines[1].x = (0., 10.)
  assert primary_edge_candidate(m).reason == 'malformedGeometry'
