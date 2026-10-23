#!/bin/sh
set -eu
if [ "$#" -lt 1 ]; then echo "Usage: $0 APK_PATH [ADB_SERIAL]" >&2; exit 2; fi
apk_path=$1
if [ "$#" -ge 2 ]; then exec adb -s "$2" install -r "$apk_path"; fi
exec adb install -r "$apk_path"
