"""Read /v2/pair into a bounded local calibration/replay dataset. Never sends control."""
import argparse
import base64
import io
import json
from pathlib import Path
import time
import urllib.request
from PIL import Image


def main():
  p=argparse.ArgumentParser()
  p.add_argument('--url',required=True,help='C3 bridge origin, e.g. http://192.168.x.x:8767')
  p.add_argument('--token-file',type=Path,required=True)
  p.add_argument('--output',type=Path,required=True)
  p.add_argument('--pairs',type=int,default=30)
  p.add_argument('--interval',type=float,default=2.0,help='seconds between pairs; leave time to reposition the stationary board')
  a=p.parse_args()
  if not 1<=a.pairs<=100:p.error('pairs must be 1..100')
  if not .5<=a.interval<=10:p.error('interval must be .5..10 seconds')
  token=a.token_file.read_text().strip()
  if len(token)<32:p.error('invalid connection code')
  a.output.mkdir(parents=True,exist_ok=False)
  for i in range(a.pairs):
    request=urllib.request.Request(a.url.rstrip('/')+'/v2/pair',headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(request,timeout=5) as response:
      body=response.read(3_000_001)
    if len(body)>3_000_000:raise ValueError('oversized pair')
    pair=json.loads(body)
    if pair['version']!=2:raise ValueError('wrong version')
    for camera in ('wide','narrow'):
      frame=pair[camera]
      if frame.get('camera_id')!=camera:raise ValueError('wrong camera identity')
      jpeg=base64.b64decode(frame.pop('jpeg_b64'),validate=True)
      with Image.open(io.BytesIO(jpeg)) as image:
        if image.size!=(frame['width'],frame['height']):raise ValueError('dimension mismatch')
        image.verify()
      name=f'{i:04d}-{camera}.jpg';(a.output/name).write_bytes(jpeg);frame['image_file']=name
    (a.output/f'{i:04d}.json').write_text(json.dumps(pair,indent=2))
    print('saved pair',i+1,flush=True)
    time.sleep(a.interval)


if __name__=='__main__':main()
