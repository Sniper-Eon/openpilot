#!/bin/sh
set -eu
sudo -n install -m 644 /data/phone-vision/phone-vision-bridge.service /run/systemd/system/phone-vision-bridge.service
sudo -n systemctl daemon-reload
sudo -n systemctl start phone-vision-bridge.service
