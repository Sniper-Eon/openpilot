import json
from pathlib import Path
import subprocess
import sys
import cv2
import numpy as np


def test_archive_import_never_creates_speed_or_live_clearance(tmp_path):
  source=tmp_path/'in';source.mkdir();video=source/'2026-10-24_12-00-00-left_repeater.mp4'
  writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),10,(320,200))
  assert writer.isOpened()
  for i in range(30):writer.write(np.full((200,320,3),i*5,np.uint8))
  writer.release()
  tool=Path(__file__).resolve().parents[1]/'stereo/import_teslacam.py'
  result=subprocess.run([sys.executable,str(tool),str(source),'--output',str(tmp_path/'out'),'--timezone','Asia/Shanghai','--max-frames','3'],capture_output=True,text=True)
  assert result.returncode==0,result.stderr
  manifest=json.loads((tmp_path/'out/manifest.json').read_text())
  assert len(manifest['frames'])==3 and manifest['live_camera_connected'] is False
  for row in manifest['frames']:
    assert row['source_kind']=='teslacam_archive' and row['telemetry_synchronized'] is False
    assert row['speed_mps'] is None and row['distance_m'] is None
    assert row['rear_clearance_authorized'] is False and row['control_eligible'] is False
