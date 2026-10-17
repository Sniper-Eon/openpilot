"""Offline JSONL consumer; no messaging, CAN, Params or control integration."""
import argparse
import json
from pathlib import Path
from openpilot.sunnypilot.overtake_observer.motion import Tracker
from openpilot.sunnypilot.overtake_observer.overtake import OvertakeShadow

def replay(rows):
  tracker=Tracker();plan=OvertakeShadow()
  for r in rows:
    stamp=r['capture_mono_ns'];route=r['route']
    if tracker.route is not None and route!=tracker.route:plan=OvertakeShadow()
    observations=tracker.update(route,stamp,r.get('detections',[]))
    # Real adapters must supply measured local evidence; missing fields stay unknown.
    evidence=dict(r.get('shadow_evidence') or {});evidence['mono_ns']=stamp
    yield {'route':route,'frame_id':r.get('frame_id'),'capture_mono_ns':stamp,
           'tracks':observations,'shadow':plan.update(evidence),'control_authorized':False}

def main(argv=None):
  p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('output',type=Path);a=p.parse_args(argv)
  rows=(json.loads(l) for l in a.input.open() if l.strip())
  with a.output.open('x') as f:
    for record in replay(rows):f.write(json.dumps(record,allow_nan=False)+'\n')
if __name__=='__main__':main()
