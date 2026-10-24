"""Local TeslaCam archive importer. Does not access the vehicle or provide live BSM."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
import cv2

PATTERN=re.compile(r'^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})-(left_repeater|right_repeater|back)\.mp4$',re.I)


def main():
  p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True)
  p.add_argument('--timezone',required=True,help='timezone used in clip filenames; does not establish telemetry synchronization')
  p.add_argument('--max-frames',type=int,default=300);a=p.parse_args();tz=ZoneInfo(a.timezone)
  if not 1<=a.max_frames<=1200:p.error('max frames must be 1..1200')
  a.output.mkdir(parents=True,exist_ok=False);count=0;rows=[];errors=[];seen=set()
  for path in sorted(a.input.rglob('*.mp4')):
    match=PATTERN.fullmatch(path.name)
    if not match:continue
    start=datetime.datetime.strptime(match[1],'%Y-%m-%d_%H-%M-%S').replace(tzinfo=tz)
    cap=cv2.VideoCapture(str(path))
    try:
      fps=cap.get(cv2.CAP_PROP_FPS)
      if not cap.isOpened() or not 1<=fps<=120:raise ValueError('archive_not_decodable_or_invalid_fps')
      stride=max(1,round(fps));index=0
      while count<a.max_frames:
        ok,frame=cap.read()
        if not ok:break
        if index%stride==0:
          offset_ms=cap.get(cv2.CAP_PROP_POS_MSEC)
          if offset_ms<0:raise ValueError('invalid_container_timestamp')
          ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,90])
          if not ok:raise ValueError('jpeg_encode_failed')
          blob=jpeg.tobytes();digest=hashlib.sha256(blob).hexdigest()
          if digest not in seen:
            name=f'{count:05d}-{match[2].lower()}.jpg';(a.output/name).write_bytes(blob);seen.add(digest)
            rows.append(dict(image=name,sha256=digest,source_file=str(path.resolve()),camera=match[2].lower(),
                             frame_index=index,container_offset_ms=offset_ms,
                             nominal_wall_time=(start+datetime.timedelta(milliseconds=offset_ms)).isoformat(),
                             source_kind='teslacam_archive',telemetry_synchronized=False,
                             distance_m=None,speed_mps=None,control_eligible=False,rear_clearance_authorized=False))
            count+=1
        index+=1
    except (ValueError,cv2.error) as error:errors.append(dict(file=str(path),error=str(error)))
    finally:cap.release()
    if count>=a.max_frames:break
  manifest=dict(purpose='offline_annotation_training_only',frames=rows,errors=errors,
                live_camera_connected=False,vehicle_modified=False,filename_timezone=a.timezone)
  (a.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
  print(f'Imported {count} frames for offline review only; no speed labels generated.')


if __name__=='__main__':main()
