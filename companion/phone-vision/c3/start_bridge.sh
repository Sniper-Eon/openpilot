#!/bin/sh
set -eu
cd /data/openpilot
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/data/phone-vision/pydeps:/data/wide-capture/pydeps:/data/openpilot
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
exec nice -n 10 /usr/local/venv/bin/python /data/phone-vision/phone_vision_bridge.py --token-file /data/phone-vision/connection-code --roi /data/phone-vision/roi.json --hz 8
