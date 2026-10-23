import json
import pytest
from phone_vision_bridge import FrameStore, read_observation, MAX_AGE_NS


def started(tmp_path):
  now=[10_000_000_000];store=FrameStore(tmp_path/'phone.json',lambda:now[0])
  store.publish(dict(capture_mono_ns=now[0],frame_id=1,jpeg_b64='fixture'))
  return store,now


def accept(store):
  packet=store.issue()
  store.accept(dict(request_id=packet['request_id'],frame_id=packet['frame_id'],left=None,right=None))


def test_startup_clears_previous_process_valid_result(tmp_path):
  p=tmp_path/'phone.json';p.write_text(json.dumps({'valid':True}))
  store=FrameStore(p,lambda:10_000_000_000)
  assert not json.loads(p.read_text())['valid']


@pytest.mark.parametrize('camera_alive',[False,True])
def test_camera_or_phone_stall_produces_unknown_not_clear(tmp_path,camera_alive):
  store,now=started(tmp_path);accept(store);now[0]+=MAX_AGE_NS+1
  if camera_alive:store.publish(dict(capture_mono_ns=now[0],frame_id=2,jpeg_b64='fixture'))
  store.expire();data=json.loads(store.output.read_text())
  assert data['status']=='unknown' and not data['valid']
  assert data['reason'].startswith('phone_result' if camera_alive else 'camera')
  assert data['updated_mono_ns']==10_000_000_000
  for _ in range(10):store.expire()
  assert not read_observation(store.output,now[0])['valid']


def test_reader_expires_result_when_bridge_itself_is_killed(tmp_path):
  store,now=started(tmp_path);accept(store)
  assert read_observation(store.output,now[0])['valid']
  # No watchdog or producer call: emulate a frozen/killed process.
  assert not read_observation(store.output,now[0]+MAX_AGE_NS+1)['valid']
  assert not read_observation(store.output,now[0]-1)['valid']


def test_camera_reconnect_invalidates_inflight_requests_and_old_stream(tmp_path):
  store,now=started(tmp_path);old=store.issue();store.new_stream()
  with pytest.raises(ValueError):store.accept(dict(request_id=old['request_id'],frame_id=1,left=None,right=None))
  assert not read_observation(store.output,now[0])['valid']
  now[0]+=200_000_000;store.publish(dict(capture_mono_ns=now[0],frame_id=1,jpeg_b64='new'))
  assert store.issue()['stream_id']!=old['stream_id']
  accept(store);assert read_observation(store.output,now[0])['valid']


@pytest.mark.parametrize('text',['[]','{','null','{"valid":true}','x'*16385])
def test_malformed_phone_result_is_never_available(tmp_path,text):
  p=tmp_path/'phone.json';p.write_text(text)
  assert not read_observation(p,10_000_000_000)['valid']
