from dataclasses import replace
import pytest
from openpilot.sunnypilot.navassist.lane_intent import (
 NavLanePlan,NavLaneIntentCoordinator,LaneTopologyInput,LaneVehicleInput,
 LaneIntentDirection,ObservedLaneChangeState,
)
P=NavLanePlan(True,'session',1,10,3,(2,))
GAP=replace(P,valid=False,recommended_indices=(),observation_interrupted=True)
TOPO=LaneTopologyInput(True,3,1,True,True,True,True)
CAR=LaneVehicleInput(True,15)
class Run:
 def __init__(self):self.c=NavLaneIntentCoordinator();self.ns=0
 def tick(self,p=P,t=TOPO,v=CAR,allow=True):
  self.ns+=50_000_000;return self.c.update(p,t,v,now_ns=self.ns,allow_new_lane_change=allow)
 def active(self):
  for _ in range(12):i=self.tick()
  assert i.signal_requested
  return i
 def lost(self):
  i=self.tick(GAP);assert not i.signal_requested and not i.lane_change_ready
  assert i.reason=='lanePositionUnavailable';assert self.c._blocked_key is None
  return i
 def recover(self):
  for _ in range(61):i=self.tick();assert not i.signal_requested and not i.lane_change_ready
  assert i.reason=='lanePositionRecovered'
  return self.active()

def test_loss_immediately_removes_lamp_and_permission_then_new_request_needs_feedback():
 r=Run();first=r.active();r.lost();second=r.recover()
 assert second.request_id>first.request_id and not second.lane_change_ready
 for _ in range(50):i=r.tick();assert not i.lane_change_ready
 for _ in range(8):i=r.tick(v=replace(CAR,right_blinker=True))
 assert i.lane_change_ready

def test_interrupted_recovery_restarts_three_second_stability():
 r=Run();r.active();r.lost()
 for _ in range(50):assert not r.tick().signal_requested
 r.tick(GAP)
 for _ in range(60):i=r.tick();assert not i.signal_requested
 assert i.reason=='lanePositionRecoveryStabilizing'
 assert r.tick().reason=='lanePositionRecovered'

@pytest.mark.parametrize('changes',[{'gas_pressed':True},{'brake_pressed':True},{'lateral_active':False},{'speed_mps':5},{'speed_mps':35},{'steering_pressed':True}])
def test_driver_or_vehicle_health_cancellation_never_rearms(changes):
 r=Run();r.active();r.lost();i=r.tick(v=replace(CAR,**changes));assert not i.signal_requested
 assert r.c._blocked_key==('session',1,10)
 for _ in range(100):assert not r.tick().signal_requested

@pytest.mark.parametrize('kwargs',[{'right_crossing_allowed':False},{'right_neighbor_exists':None},{'right_neighbor_exists':False},{'valid_for_control':False}])
def test_no_recovery_through_missing_neighbor_solid_or_stale_geometry(kwargs):
 r=Run();r.active();r.lost()
 for _ in range(100):i=r.tick(t=replace(TOPO,**kwargs));assert not i.signal_requested
 assert i.reason=='lanePositionRecoveryWaiting'

def test_blindspot_prevents_recovery():
 r=Run();r.active();r.lost()
 for _ in range(100):assert not r.tick(v=replace(CAR,right_blindspot=True)).signal_requested

def test_same_lamp_must_release_before_recovery_stability_starts():
 r=Run();r.active();r.lost()
 for _ in range(80):assert r.tick(v=replace(CAR,right_blinker=True)).reason=='lanePositionRecoveryWaiting'
 for _ in range(60):assert not r.tick().signal_requested
 assert r.tick().reason=='lanePositionRecovered'

@pytest.mark.parametrize('kwargs',[{'left_blinker':True},{'left_blinker':True,'right_blinker':True}])
def test_conflicting_driver_signal_blocks_event(kwargs):
 r=Run();r.active();r.lost();assert r.tick(v=replace(CAR,**kwargs)).reason=='lanePositionDriverSignal'
 for _ in range(100):assert not r.tick().signal_requested

def test_direction_reversal_aborts_instead_of_changing_direction():
 r=Run();r.active();r.lost();assert r.tick(replace(P,recommended_indices=(0,))).reason=='lanePositionChangedDirection'

def test_timeout_blocks_further_attempts():
 r=Run();r.active();r.lost()
 for _ in range(201):i=r.tick(GAP)
 assert i.reason=='lanePositionRecoveryTimeout'
 for _ in range(100):assert not r.tick().signal_requested

def test_route_change_cannot_resume_old_request():
 r=Run();r.active();r.lost();assert r.tick(replace(P,session_id='other')).reason=='lanePositionRouteChanged'
 assert r.c._plan_recovery_key is None

def test_no_recovery_after_lane_change_has_started():
 r=Run();r.active();i=r.tick(v=replace(CAR,right_blinker=True,lane_change_state=ObservedLaneChangeState.starting,lane_change_direction=LaneIntentDirection.right));assert i.lane_change_ready
 i=r.tick(GAP,v=replace(CAR,right_blinker=True,lane_change_state=ObservedLaneChangeState.starting,lane_change_direction=LaneIntentDirection.right))
 assert i.reason=='health' and r.c._plan_recovery_key is None and r.c._blocked_key is not None

def test_already_recommended_requires_no_retry():
 r=Run();r.active();r.lost();i=r.tick(replace(P,recommended_indices=(1,)));assert i.reason=='alreadyInRecommendedLane' and not i.signal_requested

def test_retry_limit_and_new_event_reset():
 r=Run();r.active()
 for _ in range(2):r.lost();r.recover()
 i=r.tick(GAP);assert i.reason=='lanePositionRetryLimit'
 for _ in range(100):assert not r.tick().signal_requested
 p=replace(P,maneuver_event_id=11)
 for _ in range(12):i=r.tick(p)
 assert i.signal_requested and r.c._plan_recovery_count==0

def test_unclassified_invalid_plan_retains_original_hard_abort():
 r=Run();r.active();i=r.tick(replace(GAP,observation_interrupted=False));assert i.reason=='health' and r.c._blocked_key is not None

def test_navigation_invalid_during_recovery_is_a_hard_cancel():
 r=Run();r.active();r.lost();i=r.tick(replace(GAP,observation_interrupted=False));assert i.reason=='lanePositionNavigationUnavailable'

def test_turn_handoff_cancels_recovery():
 r=Run();r.active();r.lost();assert r.tick(allow=False).reason=='lanePositionRecoveryCancelled'

@pytest.mark.parametrize('nav_valid,healthy,recommended,expected',[
 (True,True,True,True),(False,True,True,False),(True,False,True,False),(True,True,False,False),
])
def test_planner_classifies_only_fresh_recommended_observation_loss(nav_valid,healthy,recommended,expected):
 from types import SimpleNamespace as N
 from openpilot.sunnypilot.navassist.nav_lane_intentd import build_lane_plan
 nav=N(valid=nav_valid,stale=False,sessionId='s',routeRevision=1,maneuverEventId=9,maneuver='keepRight',maneuverDistanceM=500,lanes=[N(index=i,recommended=(i>0 and recommended)) for i in range(4)])
 p=build_lane_plan(nav,N(visibleLaneCount=2,egoLaneIndexFromLeft=0),healthy=healthy,amap_ego_index=None)
 assert not p.valid and p.observation_interrupted==expected
