#!/usr/bin/env python3
"""Replay images/video on the offboard host; never connects to vehicle controls."""
import argparse
import json
from pathlib import Path
import time
import uuid

import cv2
import numpy as np

from openpilot.sunnypilot.lane_topology.external.perception import YOLOPv2


def main():
  parser=argparse.ArgumentParser(description=__doc__)
  parser.add_argument('source',type=Path)
  parser.add_argument('--weights',required=True)
  parser.add_argument('--output',type=Path,required=True)
  parser.add_argument('--ego-x',type=float,default=0.5)
  parser.add_argument('--ego-y',type=float,default=0.65,help='Offline reference row, not an automatic camera calibration')
  parser.add_argument('--max-frames',type=int,default=30)
  args=parser.parse_args()
  if not 1 <= args.max_frames <= 1000:parser.error('max-frames must be 1..1000')
  model=YOLOPv2(args.weights)
  args.output.mkdir(parents=True,exist_ok=True)
  image=cv2.imread(str(args.source))
  capture=None if image is not None else cv2.VideoCapture(str(args.source))
  if image is None and not capture.isOpened():parser.error('input cannot be decoded')
  session=uuid.uuid4().hex
  latencies=[]
  with (args.output/'observations.jsonl').open('w') as log:
    for index in range(args.max_frames):
      if capture is not None:
        if index:
          capture.set(cv2.CAP_PROP_POS_MSEC,index*1000)
        ok,image=capture.read()
        if not ok:break
      frame={'version':1,'session':session,'sequence':index+1,'frame_id':index,
             'capture_mono_ns':time.monotonic_ns(),'camera':'wideRoad','ego_point':[args.ego_x,args.ego_y]}
      result=model.infer(image,frame)
      log.write(json.dumps(result,allow_nan=False)+'\n')
      latencies.append(result['inference_ms'])
      preview=image.copy();h,w=preview.shape[:2]
      for line in result['boundaries']:
        points=np.array([[round(x*w),round(y*h)] for x,y in line],np.int32)
        cv2.polylines(preview,[points],False,(0,255,255),3)
      cv2.circle(preview,(round(args.ego_x*w),round(args.ego_y*h)),7,(0,0,255),-1)
      label=(f"VISIBLE {result['ego_lane_index']+1}/{result['visible_lane_count']}" if result['valid'] else 'UNKNOWN')
      cv2.putText(preview,label+' - display only',(20,35),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,255,255),2)
      cv2.imwrite(str(args.output/f'frame-{index:04d}.jpg'),preview)
      if capture is None:break
  if capture is not None:capture.release()
  if not latencies:raise SystemExit('no frames decoded')
  report={'frames':len(latencies),'mean_ms':float(np.mean(latencies)),
          'p95_ms':float(np.percentile(latencies,95)),'absolute_lane_confirmed':False}
  (args.output/'benchmark.json').write_text(json.dumps(report,indent=2))
  print(json.dumps(report))


if __name__=='__main__':main()
