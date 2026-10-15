import base64
import copy
from dataclasses import replace
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import requests

from openpilot.sunnypilot.lane_topology.external.protocol import ResultCache, validate_frame, validate_result
from openpilot.sunnypilot.lane_topology.external.perception import observation, trace_boundaries
from openpilot.sunnypilot.lane_topology.external.sender import export_nv12, load_config, request_result, primary_has_budget
from openpilot.sunnypilot.lane_topology.external.server import LaneServer
from openpilot.selfdrive.ui.sunnypilot.onroad.lane_navigation_state import LaneOverlayDisplay, lane_display_with_external


def frame():
  return {'version': 1, 'session': 'a'*32, 'sequence': 1, 'frame_id': 10,
          'capture_mono_ns': time.monotonic_ns(), 'camera': 'wideRoad', 'ego_point': [0.5, 0.72]}


def lines(xs=(0.1, 0.3, 0.6, 0.8, 0.95)):
  return [[[x, 0.5], [x, 0.9]] for x in xs]


def test_more_than_four_boundaries_produce_visible_index_without_global_claim():
  f = frame()
  r = observation(f, lines(), 20)
  assert (r['visible_lane_count'], r['ego_lane_index']) == (4, 1)
  assert not r['absolute_confirmed']
  assert validate_result(r, f, now_ns=f['capture_mono_ns']) == r


@pytest.mark.parametrize('change', [
  {'frame_id': 11}, {'session': 'b'*32}, {'sequence': 2}, {'capture_mono_ns': 3},
  {'absolute_confirmed': True}, {'score': float('nan')}, {'ego_lane_index': 9},
  {'visible_lane_count': True}, {'boundaries': [[[float('inf'), .6], [.7, .8]]]},
])
def test_invalid_or_misaligned_host_results_are_rejected(change):
  f = frame()
  r = observation(f, lines(), 20) | change
  with pytest.raises(ValueError):
    validate_result(r, f, now_ns=f['capture_mono_ns'])


@pytest.mark.parametrize('offset', [-1, 2_000_000_001])
def test_stale_and_future_results_are_rejected(offset):
  f = frame()
  with pytest.raises(ValueError):
    validate_result(observation(f, lines(), 20), f, now_ns=f['capture_mono_ns']+offset)


def test_disappearing_or_unbracketed_ego_is_unknown():
  assert not observation(frame(), [], 20)['valid']
  assert not observation(frame(), lines((.1, .3)), 20)['valid']
  assert not observation(frame(), lines((.1, .2, .3, .9)), 20)['valid']


def test_cached_result_expires_even_when_no_new_file_is_written(tmp_path):
  f = frame();r = observation(f, lines(), 20)
  p = tmp_path/'result.json';p.write_text(json.dumps(r))
  cache = ResultCache(p)
  assert cache.read(now_ns=f['capture_mono_ns'])['ego_lane_index'] == 1
  assert cache.read(now_ns=f['capture_mono_ns']+2_000_000_001) is None
  p.write_text('{corrupt');cache.next_read = 0
  assert cache.read(now_ns=f['capture_mono_ns']) is None


def test_external_ui_never_replaces_local_marking_evidence():
  d = LaneOverlayDisplay('左 实线', '可见车道 2/3', '右 虚线', 'solid', 'dashed', True)
  r = observation(frame(), lines(), 20)
  out = lane_display_with_external(d, r)
  assert out == replace(d, center='外接可见 2/4')
  assert lane_display_with_external(d, r | {'absolute_confirmed': True}) is d
  assert lane_display_with_external(d, r | {'valid': False}) is d


def test_curved_ridges_and_blank_masks():
  h, w = 384, 640
  mask = np.zeros((h,w),np.float32)
  for x in (.1,.28,.47,.67,.86):
    points = np.array([[round((x+0.12*(y-.7)**2)*w),round(y*h)] for y in np.linspace(.45,.95,70)],np.int32)
    cv2.polylines(mask,[points],False,1.0,4)
  traced = trace_boundaries(mask,np.ones_like(mask),reference_y=.72)
  assert len(traced) == 5
  assert observation(frame(),traced,20)['visible_lane_count'] == 4
  assert trace_boundaries(np.zeros_like(mask),np.ones_like(mask),reference_y=.72) == []


def test_nv12_stride_and_padding_are_not_interpreted_as_image_pixels():
  w,h,stride = 64,48,80
  uv_offset = stride*h+128
  data = np.full(uv_offset+stride*h//2,255,np.uint8)
  data[:stride*h].reshape(h,stride)[:,:w] = 100
  data[uv_offset:].reshape(h//2,stride)[:,:w] = 128
  f = SimpleNamespace(width=w,height=h,stride=stride,uv_offset=uv_offset,data=data)
  payload = export_nv12(f)
  raw = np.frombuffer(base64.b64decode(payload['nv12']),np.uint8).reshape(h*3//2,w)
  image = cv2.cvtColor(raw,cv2.COLOR_YUV2BGR_NV12)
  assert image.shape == (h,w,3)
  assert image.max()-image.min() <= 3
  with pytest.raises(ValueError):
    export_nv12(SimpleNamespace(**(vars(f) | {'data': data[:100]})))


@pytest.mark.parametrize('url', ['http://8.8.8.8:7788','https://192.168.1.2','http://u:p@192.168.1.2','http://192.168.1.2/path'])
def test_public_or_ambiguous_host_configuration_rejected(tmp_path,url):
  p=tmp_path/'config.json';p.write_text(json.dumps({'url':url,'token':'t'*64}))
  with pytest.raises(ValueError):load_config(p)


class Model:
  def __init__(self):
    self.entered=threading.Event();self.release=threading.Event();self.block=False

  def infer(self,image,f):
    assert image.shape[:2] == (48,64)
    if self.block:
      self.entered.set();self.release.wait(3)
    return observation(f,lines(),10)


@pytest.fixture
def server():
  m=Model();s=LaneServer(('127.0.0.1',0),m,'t'*64)
  t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
  yield s,m,{'url':f'http://127.0.0.1:{s.server_port}','token':'t'*64}
  m.release.set();s.shutdown();s.server_close();t.join(2)


def jpeg():
  return cv2.imencode('.jpg',np.zeros((48,64,3),np.uint8))[1].tobytes()


def test_real_http_roundtrip_and_authentication(server):
  s,m,config=server;f=frame()
  result=request_result(config,f,jpeg())
  assert result['ego_lane_index'] == 1 and s.count == 1
  with pytest.raises(ValueError):request_result(config | {'token':'bad'},frame(),jpeg())
  assert s.count == 1


def test_slow_inference_rejects_second_frame_without_queueing(server):
  s,m,config=server;m.block=True
  payload=frame() | {'jpeg':base64.b64encode(jpeg()).decode()}
  headers={'Authorization':'Bearer '+config['token']}
  first=threading.Thread(target=lambda:requests.post(config['url']+'/infer',json=payload,headers=headers,timeout=4))
  first.start();assert m.entered.wait(2)
  response=requests.post(config['url']+'/infer',json=payload,headers=headers,timeout=1)
  assert response.status_code == 429
  m.release.set();first.join(3)


def test_bad_image_does_not_invoke_perception(server):
  s,m,config=server
  response=requests.post(config['url']+'/infer',json=frame() | {'jpeg':'YWJj'},
                         headers={'Authorization':'Bearer '+config['token']},timeout=2)
  assert response.status_code == 400 and s.count == 0


@pytest.mark.parametrize('execution,dropped,expected', [(0.03,0,True),(0.06,0,False),(.02,6,False),
                                                        (float('nan'),0,False),(.02,float('inf'),False),(-1,0,False)])
def test_primary_deadline_and_drop_guard(execution,dropped,expected):
  assert primary_has_budget(SimpleNamespace(modelExecutionTime=execution,frameDropPerc=dropped)) is expected


def test_external_cannot_replace_a_wider_local_observation():
  display = LaneOverlayDisplay('left','local','right')
  result = observation(frame(),lines((.3,.7)),10)
  assert lane_display_with_external(display,result,local_visible_count=3) is display


def test_mdns_host_works_after_hotspot_changes_address(tmp_path):
  p=tmp_path/'config.json';p.write_text(json.dumps({'url':'http://my-mac.local:7788','token':'t'*64}))
  assert load_config(p)['url'] == 'http://my-mac.local:7788'


def test_discovery_rejects_spoofed_or_replayed_host():
  from openpilot.sunnypilot.lane_topology.external.discovery import reply,verify_reply
  nonce='a'*32;token='t'*64
  answer=reply(json.dumps({'version':1,'nonce':nonce}).encode(),token,7788,'192.168.1.2')
  assert verify_reply(answer,nonce,token,'192.168.1.2') == 'http://192.168.1.2:7788'
  for n,t,ip in [('b'*32,token,'192.168.1.2'),(nonce,'bad','192.168.1.2'),(nonce,token,'8.8.8.8')]:
    with pytest.raises(ValueError):verify_reply(answer,n,t,ip)


def test_udp_discovery_roundtrip():
  from openpilot.sunnypilot.lane_topology.external.discovery import DiscoveryResponder,discover
  with DiscoveryResponder('t'*64,7788,bind='127.0.0.1',port=0) as responder:
    port=responder.sock.getsockname()[1]
    assert discover('t'*64,target='127.0.0.1',port=port) == 'http://127.0.0.1:7788'


def test_real_capnp_calibration_projects_ground_below_horizon():
  from openpilot.cereal import log
  from openpilot.sunnypilot.lane_topology.external.sender import calibrated_ego_point
  calibration = log.ExtrinsicsCalibration.new_message()
  calibration.calStatus='calibrated'
  calibration.rpyCalib=[0.,0.,0.]
  calibration.wideFromDeviceEuler=[0.,0.,0.]
  calibration.height=[1.3]
  class SM(dict):
    seen=alive=valid={s:True for s in ('extrinsicsCalibration','deviceState','wideRoadCameraState')}
  sm=SM(extrinsicsCalibration=calibration.as_reader(),deviceState=SimpleNamespace(deviceType='tici'),
        wideRoadCameraState=SimpleNamespace(sensor='ar0231'))
  point=calibrated_ego_point(sm)
  assert point is not None and point[0] == pytest.approx(.5) and .5 < point[1] < .8
  calibration.height=[]
  line=log.ModelDataV2.new_message()
  for lane in line.init('laneLines',4):
    lane.x=[0.,20.];lane.z=[1.3,1.3]
  sm['extrinsicsCalibration']=calibration.as_reader();sm['modelV2']=line.as_reader()
  assert calibrated_ego_point(sm) == pytest.approx(point)


def test_raw_nv12_http_roundtrip(server):
  s,m,config=server
  raw=np.full(64*48*3//2,128,np.uint8)
  result=request_result(config,frame(),{'nv12':base64.b64encode(raw).decode(),'width':64,'height':48})
  assert result['valid'] and s.count==1


def test_raw_frame_length_is_checked_before_decode(server):
  s,m,config=server
  payload=frame()|{'nv12':'YWJj','width':640,'height':480}
  response=requests.post(config['url']+'/infer',json=payload,headers={'Authorization':'Bearer '+config['token']},timeout=2)
  assert response.status_code==400 and s.count==0
