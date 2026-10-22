from types import SimpleNamespace

import pytest

from openpilot.sunnypilot.navassist.nav_lane_intentd import build_lane_plan


def plan(ego, target, *, healthy=True, localized=True):
  nav = SimpleNamespace(
    valid=True, stale=False, sessionId='test', routeRevision=1, maneuverEventId=1,
    maneuver='continue', maneuverDistanceM=400.0,
    lanes=[SimpleNamespace(index=i, recommended=i == target) for i in range(7)],
  )
  topology = SimpleNamespace(visibleLaneCount=3, egoLaneIndexFromLeft=1)
  return build_lane_plan(nav, topology, healthy=healthy, amap_ego_index=ego if localized else None)


@pytest.mark.parametrize('ego,target,adjacent', [(5, 2, 0), (1, 4, 2)])
def test_distant_recommendation_requests_one_visible_adjacent_lane(ego, target, adjacent):
  result = plan(ego, target)
  assert result.valid and result.recommended_indices == (adjacent,)
  assert not result.heuristic
  assert not result.allow_unknown_crossing and not result.ignore_solid_boundary


@pytest.mark.parametrize('healthy,localized', [(False, True), (True, False), (False, False)])
def test_distant_recommendation_needs_health_and_absolute_localization(healthy, localized):
  assert not plan(5, 2, healthy=healthy, localized=localized).valid


def test_current_recommended_lane_is_preserved():
  assert plan(3, 3).recommended_indices == (1,)
