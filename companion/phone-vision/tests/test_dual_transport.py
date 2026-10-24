import json
import threading
import time
import urllib.request
import urllib.error
import pytest
from dual_camera_store import DualCameraStore
from phone_vision_bridge import BridgeServer, FrameStore,camera_service_name,camera_stream_type


def test_camera_names_support_actual_device_schema_and_legacy_schema():
  class Modern:
    VISION_STREAM_NARROW_ROAD=1
    VISION_STREAM_WIDE_ROAD=2
  class Legacy:
    VISION_STREAM_ROAD=3
  assert camera_service_name('narrow',{'narrowRoadCameraState','wideRoadCameraState'})=='narrowRoadCameraState'
  assert camera_service_name('narrow',{'roadCameraState'})=='roadCameraState'
  assert camera_service_name('narrow',{'wideRoadCameraState'}) is None
  assert camera_stream_type('narrow',Modern)==1 and camera_stream_type('wide',Modern)==2
  assert camera_stream_type('narrow',Legacy)==3
  with pytest.raises(ValueError):camera_stream_type('wide',Legacy)


def test_parked_capture_keeps_profile_without_inventing_live_ground_pose(tmp_path,monkeypatch):
  import sys
  from types import SimpleNamespace
  import numpy as np
  import phone_vision_bridge as bridge
  class Streams:
    VISION_STREAM_WIDE_ROAD=1
    VISION_STREAM_NARROW_ROAD=2
  cam=SimpleNamespace(width=640,height=400,focal_length=300.,intrinsics=np.array([[300.,0,320],[0,300.,200],[0,0,1.]]))
  class SM:
    seen={'deviceState':True,'carState':False,'wideRoadCameraState':True,'extrinsicsCalibration':False}
    valid=seen;alive=seen
    logMonoTime={k:time.monotonic_ns() for k in seen}
    def update(self,_):pass
    def __getitem__(self,k):
      return {'deviceState':SimpleNamespace(deviceType='tici'),'wideRoadCameraState':SimpleNamespace(sensor='fixture'),
              'extrinsicsCalibration':SimpleNamespace(calStatus='uncalibrated',height=[]),'carState':SimpleNamespace(vEgo=0.)}[k]
  modules={
      'msgq.visionipc':SimpleNamespace(VisionIpcClient=lambda *a,**k:None),
      'openpilot.cereal.visionipc':SimpleNamespace(VisionStreamType=Streams),
      'openpilot.cereal':SimpleNamespace(messaging=SimpleNamespace(SubMaster=lambda _:SM())),
      'openpilot.cereal.services':SimpleNamespace(SERVICE_LIST={'wideRoadCameraState':None}),
      'openpilot.common.transformations.camera':SimpleNamespace(DEVICE_CAMERAS={('tici','fixture'):SimpleNamespace(wide_road=cam)},
          get_view_frame_from_calib_frame=lambda *a:None,view_frame_from_device_frame=np.eye(3)),
      'openpilot.common.transformations.orientation':SimpleNamespace(rot_from_euler=lambda _:np.eye(3))}
  for name,module in modules.items():monkeypatch.setitem(sys.modules,name,module)
  client=SimpleNamespace(timestamp_eof=time.monotonic_ns(),frame_id=1)
  buf=SimpleNamespace(data=bytes(640*400*3//2),width=640,height=400,stride=640,uv_offset=640*400)
  monkeypatch.setattr(bridge,'camera_frames',lambda _:iter([(client,buf)]))
  roi=tmp_path/'roi.json';roi.write_text('{}');store=FrameStore(tmp_path/'legacy.json');store.frame_requested.set()
  bridge.capture(store,roi,4)
  assert store.latest['calibration_id'] and store.latest['camera_matrix']
  assert store.latest['ground_inverse'] is None and store.latest['view_from_calib'] is None


def pair(store, now, skew=2_000_000, frames=(1, 8)):
  for event in store.requested.values():event.clear()
  def camera():
    assert store.requested['wide'].wait(1)
    store.publish('wide',dict(frame_id=frames[0],capture_mono_ns=now[0],jpeg_b64='fixture'))
    store.publish('narrow',dict(frame_id=frames[1],capture_mono_ns=now[0]+skew,jpeg_b64='fixture'))
  thread=threading.Thread(target=camera);thread.start()
  try:return store.issue(timeout=.5)
  finally:thread.join()


def result(packet):
  return dict(pair_id=packet['pair_id'],stream_id=packet['stream_id'],
              wide_frame_id=packet['wide']['frame_id'],narrow_frame_id=packet['narrow']['frame_id'],
              tracks=[dict(track_id=1,wide_index=0,narrow_index=0,distance_m=20.,
                           relative_speed_mps=None,absolute_speed_mps=None,confidence=.8,
                           distance_source='dual_ground_estimate',control_eligible=True)])


def fixture(tmp_path):
  now=[10_000_000_000]
  return DualCameraStore(tmp_path/'dual.json',lambda:now[0]),now


def test_no_pair_reuse_or_control_authority(tmp_path):
  store,now=fixture(tmp_path);p=pair(store,now,skew=0);r=store.accept(result(p))
  assert r['control_eligible'] is False and r['clearance_authorized'] is False
  assert r['tracks'][0]['control_eligible'] is False and r['stereo_calibrated'] is False
  with pytest.raises(ValueError,match='replayed'):store.accept(result(p))
  with pytest.raises(ValueError,match='unavailable'):store.issue(timeout=.01)


@pytest.mark.parametrize('case',['stale','future','restart','wrong_frame','wrong_stream','nan','excess','fake_stereo'])
def test_reject_invalid_evidence(tmp_path,case):
  store,now=fixture(tmp_path);p=pair(store,now,skew=0);r=result(p)
  if case=='stale':now[0]+=801_000_000
  if case=='future':now[0]-=1
  if case=='restart':store.reset()
  if case=='wrong_frame':r['narrow_frame_id']=7
  if case=='wrong_stream':r['stream_id']='previous'
  if case=='nan':r['tracks'][0]['distance_m']=float('nan')
  if case=='excess':r['tracks']*=17
  if case=='fake_stereo':r['tracks'][0]['distance_source']='stereo_experimental'
  with pytest.raises(ValueError):store.accept(r)


def test_stale_result_is_explicitly_cleared(tmp_path):
  store,now=fixture(tmp_path);store.accept(result(pair(store,now,skew=0)))
  now[0]+=801_000_000;store.expire()
  data=json.loads(store.output.read_text());assert data['valid'] is False and data['tracks']==[]


def test_stereo_requires_same_explicitly_approved_calibration_and_is_still_observation(tmp_path):
  now=[10_000_000_000];store=DualCameraStore(tmp_path/'dual.json',lambda:now[0],stereo_sha256='b'*64)
  packet=pair(store,now,skew=0);r=result(packet);r['tracks'][0]['distance_source']='stereo_experimental'
  r['stereo_calibration_sha256']='a'*64
  with pytest.raises(ValueError,match='calibration_not_approved'):store.accept(r)
  now[0]+=100_000_000;packet=pair(store,now,skew=0,frames=(2,9));r=result(packet)
  r['tracks'][0]['distance_source']='stereo_experimental';r['stereo_calibration_sha256']='b'*64
  accepted=store.accept(r)
  assert accepted['stereo_calibrated'] is True and accepted['control_eligible'] is False
  assert accepted['tracks'][0]['clearance_authorized'] is False


def test_nearest_capture_required_and_both_new(tmp_path):
  store,now=fixture(tmp_path)
  with pytest.raises(ValueError):pair(store,now,skew=100_000_000)
  now[0]+=200_000_000
  p=pair(store,now,skew=0,frames=(2,9));assert p['skew_ms']==0


def test_legacy_http_and_separate_dual_output(tmp_path):
  store,now=fixture(tmp_path);legacy=FrameStore(tmp_path/'legacy.json',lambda:now[0]);before=legacy.output.read_bytes()
  with BridgeServer(('127.0.0.1',0),'a'*32,legacy,store) as server:
    threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_address[1]}'
    with pytest.raises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+'/v2/pair')
    assert error.value.code==401
    def producer():
      assert store.requested['wide'].wait(1)
      for c in ('wide','narrow'):store.publish(c,dict(frame_id=1,capture_mono_ns=now[0],jpeg_b64='fixture'))
    thread=threading.Thread(target=producer);thread.start();headers={'Authorization':'Bearer '+'a'*32}
    p=json.load(urllib.request.urlopen(urllib.request.Request(base+'/v2/pair',headers=headers)));thread.join()
    request=urllib.request.Request(base+'/v2/observation',headers=headers,data=json.dumps(result(p)).encode())
    assert json.load(urllib.request.urlopen(request))['control_eligible'] is False
    assert legacy.output.read_bytes()==before
    server.shutdown()
