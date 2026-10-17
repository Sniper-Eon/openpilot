import unittest,itertools
import numpy as np
from openpilot.sunnypilot.overtake_observer.motion import Tracker,velocity,linear_sum_assignment
from openpilot.sunnypilot.overtake_observer.overtake import OvertakeShadow

def det(x=100,dist=30,cls=3):return {'bbox_xyxy':[x,100,x+50,150],'class_id_raw':cls,'ground_candidate':None if dist is None else [dist,0]}
class MotionTests(unittest.TestCase):
 def test_assignment_matches_exhaustive(self):
  rng=np.random.default_rng(35)
  for n,m in ((1,2),(2,1),(2,3),(3,2),(4,4)):
   a=rng.random((n,m));i,j=linear_sum_assignment(a);score=sum(a[x,y] for x,y in zip(i,j))
   if n<=m:expected=min(sum(a[x,y] for x,y in enumerate(p)) for p in itertools.permutations(range(m),n))
   else:expected=min(sum(a[x,y] for y,x in enumerate(p)) for p in itertools.permutations(range(n),m))
   self.assertAlmostEqual(score,expected)
 def test_constant_relative_approach(self):
  t=Tracker();out=None
  for i in range(4):out=t.update('r',i*10**9,[det(100+i,30-2*i)])[0]
  self.assertAlmostEqual(out['metric_motion']['candidate_relative_forward_mps'],-2);self.assertIsNone(out['relative_speed_mps']);self.assertFalse(out['valid_for_control'])
 def test_metric_estimate_not_available_immediately(self):
  t=Tracker();r=t.update('r',0,[det()])[0];self.assertEqual(r['metric_motion']['state'],'unknown')
 def test_ground_loss_clears_old_velocity(self):
  t=Tracker()
  for i in range(3):t.update('r',i*10**9,[det(100,30-i)])
  r=t.update('r',3*10**9,[det(100,None)])[0];self.assertEqual(r['metric_motion']['state'],'unknown')
  r=t.update('r',4*10**9,[det(100,26)])[0];self.assertEqual(r['metric_motion']['state'],'unknown')
 def test_gap_changes_identity(self):
  t=Tracker();a=t.update('r',0,[det()])[0];b=t.update('r',3*10**9,[det()])[0];self.assertNotEqual(a['track_id'],b['track_id'])
 def test_route_changes_identity(self):
  t=Tracker();a=t.update('a',10,[det()])[0];b=t.update('b',1,[det()])[0];self.assertNotEqual(a['track_id'],b['track_id'])
 def test_missing_detection_no_reidentification(self):
  t=Tracker();a=t.update('r',0,[det()])[0];t.update('r',10**9,[]);b=t.update('r',2*10**9,[det()])[0];self.assertNotEqual(a['track_id'],b['track_id'])
 def test_backward_or_duplicate_time_rejected(self):
  t=Tracker();t.update('r',100,[det()])
  for timestamp in (100,99):
   with self.assertRaises(ValueError):t.update('r',timestamp,[det()])
 def test_class_change_no_identity_link(self):
  t=Tracker();a=t.update('r',0,[det()])[0];b=t.update('r',10**9,[det(cls=4)])[0];self.assertNotEqual(a['track_id'],b['track_id'])
 def test_ambiguous_merge_does_not_guess(self):
  t=Tracker();a=t.update('r',0,[det(100),det(102)]);b=t.update('r',10**9,[det(101)])[0];self.assertNotIn(b['track_id'],[x['track_id'] for x in a])
 def test_inconsistent_motion_unknown(self):
  r=velocity([{'mono_ns':i*10**9,'ground_candidate':[x,0]} for i,x in enumerate((20,70,10,60))]);self.assertEqual(r['state'],'unknown')
 def test_plan_full_synthetic_sequence(self):
  p=OvertakeShadow();obs={'observation_valid':True,'bsm_warning':False,'local_lane_crossing_confirmed':True,'rear_gap_verified':True,'front_gap_verified':True,'lead_slower_confirmed':True}
  expected=['prepare_pass','passing','prepare_return','following']
  for i,update in enumerate(({}, {'adjacent_lane_entry_confirmed':True},{'passed_target_confirmed':True},{'return_lane_entry_confirmed':True})):
   r=p.update(dict(obs,mono_ns=i*10**9,**update));self.assertEqual(r['phase'],expected[i]);self.assertFalse(r['control_authorized']);self.assertIsNone(r['actuator_command'])
 def test_unknown_bsm_cannot_prepare(self):
  p=OvertakeShadow();r=p.update({'mono_ns':0,'observation_valid':True,'rear_gap_verified':True,'front_gap_verified':True,'local_lane_crossing_confirmed':True,'lead_slower_confirmed':True});self.assertEqual(r['phase'],'waiting_evidence')
 def test_alarm_during_pass_requests_handover(self):
  p=OvertakeShadow();p.phase='passing';r=p.update({'mono_ns':0,'observation_valid':True,'bsm_warning':True});self.assertEqual(r['phase'],'waiting_or_handover');self.assertIsNone(r['actuator_command'])
 def test_driver_cancel(self):
  r=OvertakeShadow().update({'mono_ns':0,'driver_cancel':True});self.assertEqual(r['phase'],'cancelled')
 def test_cancel_is_latched(self):
  p=OvertakeShadow();p.update({'mono_ns':0,'driver_cancel':True});r=p.update({'mono_ns':10**9,'observation_valid':True,'bsm_warning':False,'front_gap_verified':True,'rear_gap_verified':True,'local_lane_crossing_confirmed':True,'lead_slower_confirmed':True});self.assertEqual(r['phase'],'cancelled')
 def test_state_not_kept_after_long_gap(self):
  p=OvertakeShadow();p.update({'mono_ns':0});p.phase='passing';r=p.update({'mono_ns':10**10,'observation_valid':True,'bsm_warning':False});self.assertEqual(r['phase'],'waiting_evidence')
 def test_no_rear_gap_no_overtake(self):
  p=OvertakeShadow();r=p.update({'mono_ns':0,'observation_valid':True,'bsm_warning':False,'rear_gap_verified':False,'front_gap_verified':True,'local_lane_crossing_confirmed':True,'lead_slower_confirmed':True});self.assertEqual(r['phase'],'waiting_evidence')
if __name__=='__main__':unittest.main(verbosity=2)
