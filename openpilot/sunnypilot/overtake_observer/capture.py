"""Explicit, bounded VisionIPC recording. No control publishers or old-file pruning."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import shutil
import time
import uuid

SERVICES=('carState','modelV2','extrinsicsCalibration','wideRoadCameraState','deviceState')
CAR_FIELDS=('vEgo','aEgo','yawRate','steeringAngleDeg','steeringPressed','brakePressed',
            'gasPressed','leftBlinker','rightBlinker','leftBlindspot','rightBlindspot','canValid')

class BoundedWriter:
  def __init__(self,root:Path,max_bytes:int,min_free:int=2*1024**3):
    self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False)
    self.max_bytes,self.min_free=max_bytes,min_free;self.total=0;self.stream=None
    self.path=self.root/'frames.partial'
  def write(self,record):
    data=(json.dumps(record,allow_nan=False,separators=(',',':'))+'\n').encode()
    if self.total+len(data)>self.max_bytes:raise OSError('byte_limit')
    if shutil.disk_usage(self.root).free<self.min_free:raise OSError('disk_reserve')
    if self.stream is None:
      self.stream=self.path.open('xb');self.path.chmod(0o600)
    self.stream.write(data);self.stream.flush();self.total+=len(data)
  def close(self):
    if self.stream is not None:
      self.stream.close();self.stream=None;self.path.rename(self.root/'frames.jsonl')

def primary_ready(alive,valid,execution,drops,thermal):
  return (alive is True and valid is True and type(execution) in (int,float)
          and math.isfinite(execution) and 0<=execution<=.045
          and type(drops) in (int,float) and math.isfinite(drops) and 0<=drops<=5
          and type(thermal) is int and 0<=thermal<2)

def arguments(argv=None):
  p=argparse.ArgumentParser(description=__doc__)
  p.add_argument('--hz',type=float,default=10)
  p.add_argument('--seconds',type=float,default=120)
  p.add_argument('--wait-seconds',type=float,default=600)
  p.add_argument('--max-mib',type=int,default=512)
  p.add_argument('--root',type=Path,default=Path('/data/media/0/motion-evidence'))
  a=p.parse_args(argv)
  if not math.isfinite(a.hz) or not 1<=a.hz<=20:p.error('hz must be 1..20')
  if not math.isfinite(a.seconds) or not 1<=a.seconds<=180:p.error('seconds must be 1..180')
  if not math.isfinite(a.wait_seconds) or not 1<=a.wait_seconds<=1800:p.error('wait-seconds must be 1..1800')
  if not 16<=a.max_mib<=1024:p.error('max-mib must be 16..1024')
  return a

def main(argv=None):
  a=arguments(argv)
  # Imports only at execution: unit tests and --help need no attached device.
  from msgq.visionipc import VisionIpcClient
  from openpilot.cereal import messaging
  from openpilot.cereal.visionipc import VisionStreamType
  from openpilot.common.params import Params
  from openpilot.sunnypilot.navassist.diagnostics import finite_values
  from openpilot.sunnypilot.lane_topology.external.sender import export_nv12
  client=VisionIpcClient('camerad',VisionStreamType.VISION_STREAM_WIDE_ROAD,conflate=True)
  sm=messaging.SubMaster(list(SERVICES));params=Params();connected=False
  session=uuid.uuid4().hex;root=a.root/f'{time.time_ns()}-{session[:8]}'
  writer=BoundedWriter(root,a.max_mib*1024**2)
  begin=time.monotonic();active=None;deadline=begin;last_stamp=0;stamps=[]
  counters={'frames':0,'stale_or_duplicate':0,'primary_guard_skips':0,'camera_timeouts':0}
  reason='completed';error=None
  try:
    while True:
      now=time.monotonic()
      if active is None and now-begin>=a.wait_seconds:reason='wait_timeout';break
      if active is not None and now-active>=a.seconds:reason='duration_limit';break
      if params.get_bool('IsOffroad'):
        if active is not None:reason='offroad';break
        time.sleep(.2);continue
      if not connected:
        connected=client.connect(False)
        if not connected:time.sleep(.2);continue
      if active is None:active=now
      time.sleep(max(0,deadline-time.monotonic()));deadline=time.monotonic()+1/a.hz
      sm.update(0)
      if not all(sm.seen[s] and sm.alive[s] and sm.valid[s] for s in ('modelV2','deviceState')):
        counters['primary_guard_skips']+=1;continue
      model=sm['modelV2'];device=sm['deviceState']
      if not primary_ready(True,True,float(model.modelExecutionTime),float(model.frameDropPerc),int(device.thermalStatus)):
        counters['primary_guard_skips']+=1;continue
      frame=client.recv(timeout_ms=100)
      if frame is None:counters['camera_timeouts']+=1;continue
      stamp=int(client.timestamp_eof);recorded=time.monotonic_ns()
      if stamp<=last_stamp or not 0<=recorded-stamp<=250_000_000:
        counters['stale_or_duplicate']+=1;continue
      last_stamp=stamp;image=export_nv12(frame);sm.update(0)
      row={'schema':'motion-capture-v1','session':session,'frame_id':int(client.frame_id),
           'capture_mono_ns':stamp,'recorded_mono_ns':recorded,'source_width':int(frame.width),
           'source_height':int(frame.height),'image':image,'services':{},'sampling_target_hz':a.hz}
      for name in SERVICES:
        if not sm.seen[name]:continue
        value=sm[name]
        if name=='carState':data={key:getattr(value,key) for key in CAR_FIELDS}
        elif name=='modelV2':data={key:getattr(value,key) for key in ('frameId','timestampEof','modelExecutionTime','frameDropPerc')}
        else:data=value.to_dict()
        log_ns=int(sm.logMonoTime[name])
        row['services'][name]={'log_mono_ns':log_ns,'capture_minus_message_ns':stamp-log_ns,
                               'alive':bool(sm.alive[name]),'valid':bool(sm.valid[name]),'data':data}
      row['bsm_note']='carState warnings only; raw SNA/freshness needs matching retained rlog'
      writer.write(finite_values(row));stamps.append(stamp);counters['frames']+=1
  except KeyboardInterrupt:reason='interrupted'
  except (OSError,ValueError) as exc:reason='capture_error';error=type(exc).__name__+': '+str(exc)
  finally:
    writer.close()
    span=(stamps[-1]-stamps[0])/1e9 if len(stamps)>1 else None
    summary={'session':session,'stop_reason':reason,'error':error,'counts':counters,'bytes':writer.total,
             'target_hz':a.hz,'observed_hz':(len(stamps)-1)/span if span and span>0 else None,
             'capture_span_s':span,'control_publishers':False,'old_files_deleted':False,
             'note':'No interpolation; asynchronous service stamps retained; target rate is not measured capacity.'}
    (root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps({'directory':str(root),**summary}),flush=True)
  return 1 if reason=='capture_error' else 0

if __name__=='__main__':raise SystemExit(main())
