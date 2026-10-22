import json,importlib.util
from pathlib import Path
from types import SimpleNamespace as N
import pytest
def load(name):
 import importlib
 return importlib.import_module('openpilot.sunnypilot.navassist.'+name)
D=load('diagnosticsd')
@pytest.mark.parametrize('data',[
 {'valid':False,'capture_mono_ns':1_000_000_000,'estimate':{'reason':'noSameDirectionAnchor'}},
 {'publish_mono_ns':1_000_000_000,'right_anchor_source':'roadEdge'},
])
def test_records_bounded_position_evidence_and_real_age(tmp_path,data):
 p=tmp_path/'evidence.json';p.write_text(json.dumps(data));r=D.read_lane_evidence(p,mono_ns=1_200_000_000)
 assert r['available'] and r['age_ms']==200 and r['data']==data
@pytest.mark.parametrize('content,error',[('[]','notObject'),('{','JSONDecodeError'),('x'*4097,'oversize')])
def test_bad_evidence_never_breaks_recording(tmp_path,content,error):
 p=tmp_path/'evidence.json';p.write_text(content);r=D.read_lane_evidence(p,mono_ns=1)
 assert not r['available'] and r['error']==error

def test_missing_and_bad_clock_are_diagnostic_values(tmp_path):
 p=tmp_path/'missing';assert not D.read_lane_evidence(p,mono_ns=1)['available']
 p.write_text('{"capture_mono_ns":true}');assert D.read_lane_evidence(p,mono_ns=1)['age_ms'] is None
 p.write_text('{"capture_mono_ns":2}');assert D.read_lane_evidence(p,mono_ns=1)['age_ms']<0

@pytest.mark.parametrize('valid',[True,False])
def test_writer_keeps_control_validity_and_adds_estimator_reason(monkeypatch,valid):
 n=load('navassistd');saved={};monkeypatch.setattr(n,'atomic_json',lambda p,v:saved.update(v))
 position={'lane_index_from_left':1,'lane_count':4,'valid':valid,'reason':None if valid else 'anchorConflict','confidence':.95 if valid else 0}
 n.write_lane_position(valid=valid,position=position,current=N(snapshot=N(session_id='s',route_revision=1)),now_ns=100,stable_samples=3)
 assert saved['valid']==valid and saved['absolute_confirmed']==valid
 assert saved['lane_index']==(2 if valid else 0)
 assert saved['estimate']==position
