import json
from pathlib import Path
import threading
import urllib.request
import urllib.error
import pytest
from phone_vision_bridge import FrameStore, BridgeServer

def fixture(tmp_path):
  now = [10_000_000_000]
  store = FrameStore(tmp_path/'observation.json', lambda: now[0])
  store.publish({'capture_mono_ns':now[0], 'frame_id':1, 'jpeg_b64':'fixture'})
  return store, now

def result(packet):
  return dict(request_id=packet['request_id'],frame_id=packet['frame_id'],left={'distance_m':20.,'relative_speed_mps':-2.,'absolute_speed_mps':13.,'hits':5},right=None)

def test_capture_clock_and_replay(tmp_path):
  store, now=fixture(tmp_path);p=store.issue();r=store.accept(result(p))
  assert r['updated_mono_ns']==10_000_000_000 and r['control_eligible'] is False
  with pytest.raises(ValueError):store.accept(result(p))

def test_stall_cannot_refresh_an_old_frame(tmp_path):
  store, now=fixture(tmp_path);p=store.issue();now[0]+=900_000_000
  with pytest.raises(ValueError):store.accept(result(p))
  with pytest.raises(ValueError):store.issue()
  store.expire()
  assert json.loads(store.output.read_text())['valid'] is False

def test_wrong_frame_and_nonfinite_rejected(tmp_path):
  store, now=fixture(tmp_path);data=result(store.issue());data['frame_id']=9
  with pytest.raises(ValueError):store.accept(data)
  data=result(store.issue());data['left']['distance_m']=float('nan')
  with pytest.raises(ValueError):store.accept(data)

def test_http_requires_connection_code_and_accepts_fresh_result(tmp_path):
  store, now=fixture(tmp_path)
  with BridgeServer(('127.0.0.1',0),'a'*32,store) as server:
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:'+str(server.server_address[1])
    with pytest.raises(urllib.error.HTTPError) as e:urllib.request.urlopen(base+'/v1/frame')
    assert e.value.code==401
    headers={'Authorization':'Bearer '+'a'*32}
    def camera():
      assert store.frame_requested.wait(1)
      now[0]+=50_000_000
      store.publish({'capture_mono_ns':now[0], 'frame_id':2, 'jpeg_b64':'fixture'})
    producer=threading.Thread(target=camera);producer.start()
    with urllib.request.urlopen(urllib.request.Request(base+'/v1/frame',headers=headers)) as response:p=json.load(response)
    producer.join()
    request=urllib.request.Request(base+'/v1/observation',data=json.dumps(result(p)).encode(),headers=headers)
    with urllib.request.urlopen(request) as response:assert json.load(response)['accepted']
    server.shutdown()


def test_camera_restart_recreates_ipc_client():
  from phone_vision_bridge import camera_frames
  now = [0.]
  created = []
  class Client:
    def __init__(self, index): self.index = index
    def connect(self, blocking): return self.index != 1
    def recv(self, timeout_ms):
      now[0] += 1
      return None if self.index == 0 else 'new-camera-frame'
  def make():
    client = Client(len(created)); created.append(client); return client
  def sleep(seconds): now[0] += seconds
  frames = camera_frames(make, lambda: now[0], sleep)
  client, frame = next(frames)
  assert len(created) == 3
  assert client is created[2] and frame == 'new-camera-frame'
  frames.close()
