from openpilot.sunnypilot.navassist.closing_risk import ClosingRiskObserver
N=10_000_000_000
def packet(t,d=20.,track=1,stream='one'):
 return dict(version=1,source='tesnav-phone',valid=True,control_eligible=False,updated_mono_ns=t,stream_id=stream,left=dict(track_id=track,hits=10,confidence=.9,distance_m=d),right=None)
def run(slope=-8.,related=()):
 o=ClosingRiskObserver()
 for i in range(7):t=N+i*200_000_000;r=o.update(packet(t,24+slope*i*.2),t,related_lanes=related)
 return o,r
def test_closing_front_vehicle_reports_risk_only_after_continuous_evidence():
 o,r=run(related=('left',));assert r['left']['state']=='closing_risk_observed'
 assert abs(r['left']['closing_mps']-8)<1e-6
 assert not r['control_eligible'] and not r['clearance_authorized']
def test_unknown_road_membership_does_not_become_confirmed_lane_warning():
 _,r=run();assert r['left']['state']=='possible_closing_risk_lane_unknown'
 assert r['rear_coverage_available'] is False
def test_receding_vehicle_does_not_warn_or_authorize_clearance():
 _,r=run(4.);assert r['left']['state']=='no_fast_closing_observed'
 assert r['left']['risk_observed'] is False and not r['left']['clearance_authorized']
def test_missing_target_is_unknown_not_a_clear_lane():
 _,r=run();assert r['right']['state']=='unknown' and not r['right']['clearance_authorized']
def test_duplicate_cannot_accumulate_history():
 o=ClosingRiskObserver()
 for _ in range(100):r=o.update(packet(N),N)
 assert r['left']['reason']=='warming_up'
def test_stale_and_future_packets_discard_previous_risk():
 o,_=run();r=o.update(packet(N),N+2_000_000_000);assert r['left']['state']=='unknown'
 assert o.update(packet(N+1),N)['left']['state']=='unknown'
def test_stream_switch_requires_new_distance_window():
 o,_=run();t=N+1_400_000_000;r=o.update(packet(t,12.,stream='two'),t);assert r['left']['reason']=='warming_up'
def test_track_switch_requires_new_distance_window():
 o,_=run();t=N+1_400_000_000;r=o.update(packet(t,12.,track=2),t);assert r['left']['reason']=='warming_up'
def test_nonfinite_distance_and_boolean_timestamp_rejected():
 o=ClosingRiskObserver();assert o.update(packet(N,float('nan')),N)['left']['reason']=='unreliable_distance'
 assert o.update(packet(True),N)['left']['state']=='unknown'
def test_large_distance_jump_does_not_create_closing_warning():
 o,_=run(0.);t=N+1_400_000_000;r=o.update(packet(t,3.),t);assert r['left']['reason']=='distance_jump'
def test_one_new_frame_cannot_immediately_confirm_fast_closing():
 o=ClosingRiskObserver();r=o.update(packet(N,3),N);assert not r['left']['risk_observed']

def test_runner_reads_bounded_json_and_does_not_touch_input(tmp_path):
 from openpilot.sunnypilot.navassist.closing_riskd import read_packet
 p=tmp_path/'input.json';raw='{"valid":false}';p.write_text(raw)
 assert read_packet(p)=={'valid':False} and p.read_text()==raw
 p.write_text('x'*17000);assert read_packet(p) is None
 assert read_packet(tmp_path/'missing') is None
