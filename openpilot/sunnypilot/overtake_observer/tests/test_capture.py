import json
import pytest
from openpilot.sunnypilot.overtake_observer.capture import BoundedWriter,primary_ready,arguments,thermal_level,MovementTrigger
from openpilot.sunnypilot.overtake_observer.projection import project_box
from openpilot.sunnypilot.overtake_observer.replay import replay

def test_capture_stops_at_budget_without_deleting(tmp_path):
  old=tmp_path/'old.jsonl';old.write_text('keep')
  writer=BoundedWriter(tmp_path/'new',max_bytes=30,min_free=0)
  writer.write({'frame_id':1})
  with pytest.raises(OSError):writer.write({'padding':'x'*100})
  writer.close();writer.close()
  assert old.read_text()=='keep';assert json.loads((tmp_path/'new/frames.jsonl').read_text())=={'frame_id':1}
  assert (tmp_path/'new/frames.jsonl').stat().st_mode&0o777==0o600

def test_existing_session_never_overwritten(tmp_path):
  with pytest.raises(FileExistsError):BoundedWriter(tmp_path,100,min_free=0)

def test_nonfinite_record_refused(tmp_path):
  w=BoundedWriter(tmp_path/'new',100,min_free=0)
  with pytest.raises(ValueError):w.write({'x':float('nan')})
  w.close();assert not list((tmp_path/'new').iterdir())

def test_primary_load_and_heat_guard():
  assert primary_ready(True,True,.03,0,0)
  for values in ((True,True,.046,0,0),(True,True,.03,6,0),(True,True,.03,0,2),(False,True,.03,0,0),(True,True,float('nan'),0,0)):
    assert not primary_ready(*values)

def test_dynamic_thermal_enum_has_no_integer_conversion():
  class Enum:
    def __str__(self):return 'green'
  assert thermal_level(Enum())==0
  assert thermal_level('red')==2
  assert thermal_level('ok')==0
  assert thermal_level('overheated')==2
  assert thermal_level('critical')==3
  assert thermal_level('unexpected')==-1

def vehicle(capture,speed=3.,offset=0,valid=True):
  return {'alive':True,'valid':valid,'log_mono_ns':capture+offset,'data':{'vEgo':speed}}

def test_stationary_never_spends_driving_window():
  t=MovementTrigger()
  assert not any(t.update(i*100_000_000,vehicle(i*100_000_000,speed=0)) for i in range(100))
  assert arguments([]).start=='moving'

def test_movement_requires_sustained_fresh_samples():
  t=MovementTrigger()
  results=[t.update(i*100_000_000,vehicle(i*100_000_000)) for i in range(6)]
  assert results==[False]*5+[True]

def test_stale_vehicle_speed_or_pause_resets_trigger():
  for bad in (vehicle(300_000_000,speed=0),vehicle(300_000_000,offset=-400_000_000),vehicle(300_000_000,valid=False)):
    t=MovementTrigger()
    for i in range(3):assert not t.update(i*100_000_000,vehicle(i*100_000_000))
    assert not t.update(300_000_000,bad)
    assert not t.update(400_000_000,vehicle(400_000_000))

@pytest.mark.parametrize('arg',[['--hz','nan'],['--hz','21'],['--seconds','3601'],['--max-mib','16384'],['--segment-seconds','nan']])
def test_invalid_recording_bounds(arg):
  with pytest.raises(SystemExit):arguments(arg)

def test_longer_capture_defaults_are_not_two_minutes():
  a=arguments([])
  assert (a.seconds,a.max_mib,a.segment_seconds,a.start)==(900,4096,60,'moving')

def test_segment_rotation_preserves_all_and_cumulative_budget(tmp_path):
  w=BoundedWriter(tmp_path/'new',max_bytes=55,min_free=0,rotate_seconds=60)
  w.write({'frame_id':1},now=0);w.write({'frame_id':2},now=61);w.write({'frame_id':3},now=122)
  with pytest.raises(OSError):w.write({'frame_id':4},now=183)
  w.close();w.close()
  files=sorted((tmp_path/'new').glob('*.jsonl'))
  assert [json.loads(p.read_text())['frame_id'] for p in files]==[1,2,3]
  assert len(w.closed_files)==3
  assert sum(p.stat().st_size for p in files)==w.total<=55

def test_analytic_ground_geometry_not_road_validation():
  matrix=[[320,800,0],[200,0,800],[1,0,0]]
  r=project_box([300,224,340,264],matrix,1.6,(640,400),geometry_valid=True)
  assert r['candidate_forward_m']==pytest.approx(20)
  assert r['candidate_right_m']==pytest.approx(0)
  assert r['valid_for_control'] is False
  assert project_box([300,140,340,180],matrix,1.6,(640,400),geometry_valid=True)['candidate_forward_m'] is None
  assert project_box([300,224,340,264],matrix,1.6,(640,400))['candidate_forward_m'] is None

def test_branch_replay_does_not_default_to_control():
  r=list(replay([{'route':'r','frame_id':1,'capture_mono_ns':0,'detections':[]}]))[0]
  assert r['shadow']['phase']=='waiting_evidence';assert r['shadow']['actuator_command'] is None
