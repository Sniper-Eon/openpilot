#!/bin/sh
set -eu
cd /data/openpilot
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/data/phone-vision/pydeps:/data/wide-capture/pydeps:/data/openpilot
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
set -- --token-file /data/phone-vision/connection-code --roi /data/phone-vision/roi.json --hz 8
# Explicit opt-in; installer never creates this flag or starts the observer.
if [ -f /data/phone-vision/dual-camera.enabled ]; then
  set -- "$@" --dual-camera
  if [ -f /data/phone-vision/stereo-calibration.json ]; then
    set -- "$@" --stereo-calibration /data/phone-vision/stereo-calibration.json
  fi
fi
exec nice -n 10 /usr/local/venv/bin/python /data/phone-vision/phone_vision_bridge.py "$@"
