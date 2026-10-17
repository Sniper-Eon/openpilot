"""Replay-only maneuver intent state machine. Emits no actuator commands."""
class OvertakeShadow:
 def __init__(self):self.phase='following';self.last=None
 def update(self,obs):
  now=obs.get('mono_ns')
  if type(now) is not int or (self.last is not None and now<=self.last):raise ValueError('capture time must increase')
  gap=self.last is not None and now-self.last>1_500_000_000
  self.last=now;reason=[]
  if obs.get('driver_cancel') is True:self.phase='cancelled';reason=['driver_cancel']
  elif self.phase=='cancelled' and obs.get('resume_simulation') is not True:
   reason=['cancellation_latched']
  elif obs.get('observation_valid') is not True or gap:self.phase='waiting_evidence';reason=['observation_invalid_or_gap']
  elif obs.get('bsm_warning') is True:self.phase='waiting_or_handover';reason=['blindspot_warning_no_automatic_countersteer']
  elif obs.get('bsm_warning') is not False:self.phase='waiting_evidence';reason=['blindspot_state_unknown']
  elif (obs.get('local_lane_crossing_confirmed') is not True or obs.get('rear_gap_verified') is not True
       or obs.get('front_gap_verified') is not True):
   self.phase='waiting_evidence';reason=['local_crossing_front_or_rear_gap_unverified']
  elif self.phase in ('following','waiting_evidence','waiting_or_handover','cancelled'):
   self.phase='prepare_pass' if obs.get('lead_slower_confirmed') is True and obs.get('driver_cancel') is not True else 'following'
  elif self.phase=='prepare_pass' and obs.get('adjacent_lane_entry_confirmed') is True:self.phase='passing'
  elif self.phase=='passing' and obs.get('passed_target_confirmed') is True:self.phase='prepare_return'
  elif self.phase=='prepare_return' and obs.get('return_lane_entry_confirmed') is True:self.phase='following'
  return {'phase':self.phase,'reasons':reason,'control_authorized':False,'actuator_command':None,'mode':'offline_shadow','thresholds_validated_for_highway':False}
