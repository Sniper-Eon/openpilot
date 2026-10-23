import threading
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from phone_vision_bridge import FrameStore, MAX_AGE_NS


def setup(tmp_path):
 now=[10_000_000_000];s=FrameStore(tmp_path/'result.json',clock=lambda:now[0]);return s,now


def test_no_client_no_encode_and_requests_are_rate_bounded(tmp_path):
 s,_=setup(tmp_path)
 for i in range(100):assert not s.claim_capture(i/100,8)
 s.frame_requested.set();assert s.claim_capture(1.,8)
 for i in range(1,12):
  s.frame_requested.set();assert not s.claim_capture(1.+i/100,8)
 assert s.frame_requested.is_set()
 assert s.claim_capture(1.13,8)
 assert not s.frame_requested.is_set()


def test_new_request_cannot_reuse_preexisting_jpeg(tmp_path):
 s,now=setup(tmp_path);s.publish(dict(capture_mono_ns=now[0],frame_id=1))
 with pytest.raises(ValueError,match='camera_unavailable'):
  s.issue(fresh=True,timeout=.01)
 assert s.frame_requested.is_set()


def test_wait_releases_lock_and_delivers_actual_new_capture(tmp_path):
 s,now=setup(tmp_path);s.publish(dict(capture_mono_ns=now[0],frame_id=1))
 with ThreadPoolExecutor(1) as pool:
  future=pool.submit(s.issue,True,.5)
  assert s.frame_requested.wait(.2)
  now[0]+=50_000_000;s.publish(dict(capture_mono_ns=now[0],frame_id=2))
  p=future.result(timeout=1)
 assert p['frame_id']==2 and p['capture_mono_ns']==now[0]
 assert p['capture_age_ms']==0 and p['bridge_wait_ms']==50.


def test_raw_camera_health_does_not_refresh_phone_results(tmp_path):
 s,now=setup(tmp_path);s.publish(dict(capture_mono_ns=now[0],frame_id=1));p=s.issue()
 s.accept(dict(request_id=p['request_id'],frame_id=1,left=None,right=None))
 now[0]+=MAX_AGE_NS+1;s.camera_seen(now[0]);s.expire()
 d=json.loads(s.output.read_text())
 assert d['valid'] is False and d['reason']=='phone_result_unavailable_or_stale'
 assert d['updated_mono_ns']<now[0]


def test_reconnect_cannot_reuse_inflight_requests(tmp_path):
 s,now=setup(tmp_path);s.publish(dict(capture_mono_ns=now[0],frame_id=1));old=s.issue()
 s.new_stream()
 with pytest.raises(ValueError,match='unknown_or_replayed_request'):
  s.accept(dict(request_id=old['request_id'],frame_id=1,left=None,right=None))
 with ThreadPoolExecutor(1) as pool:
  pending=pool.submit(s.issue,True,.5);assert s.frame_requested.wait(.2)
  now[0]+=100_000_000;s.publish(dict(capture_mono_ns=now[0],frame_id=2));new=pending.result(1)
 assert new['stream_id']!=old['stream_id'] and new['frame_id']==2


def test_one_unused_young_buffer_is_immediate_and_next_request_cannot_repeat(tmp_path):
 s,now=setup(tmp_path);s.publish(dict(capture_mono_ns=now[0],frame_id=1))
 first=s.issue(fresh=True,buffered=True,timeout=.01)
 assert first['frame_id']==1 and s.frame_requested.is_set()
 with pytest.raises(ValueError,match='camera_unavailable'):
  s.issue(fresh=True,buffered=True,timeout=.01)


def test_old_unissued_prefetch_is_not_dispatched_as_current(tmp_path):
 s,now=setup(tmp_path);s.publish(dict(capture_mono_ns=now[0],frame_id=1));now[0]+=151_000_000
 with pytest.raises(ValueError,match='camera_unavailable'):
  s.issue(fresh=True,buffered=True,timeout=.01)
 assert s.frame_requested.is_set()


def test_prefetch_work_is_one_extra_frame_not_an_idle_stream(tmp_path):
 s,now=setup(tmp_path);s.publish(dict(capture_mono_ns=now[0],frame_id=1))
 s.issue(fresh=True,buffered=True)
 assert s.claim_capture(1.,8)
 now[0]+=50_000_000;s.publish(dict(capture_mono_ns=now[0],frame_id=2))
 for t in [1.2,1.5,2.,10.]:assert not s.claim_capture(t,8)
 p=s.issue(fresh=True,buffered=True);assert p['frame_id']==2
 assert s.frame_requested.is_set()
