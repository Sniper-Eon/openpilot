import json
import pytest
from openpilot.sunnypilot.overtake_observer.capture import BoundedWriter,primary_ready,arguments
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

@pytest.mark.parametrize('arg',[['--hz','nan'],['--hz','21'],['--seconds','1000'],['--max-mib','4096']])
def test_invalid_recording_bounds(arg):
  with pytest.raises(SystemExit):arguments(arg)

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
