#!/usr/bin/env bash
set -euo pipefail

: "${TESNAV_IOS_DEVICE_ID:?Set TESNAV_IOS_DEVICE_ID to the paired CoreDevice identifier}"

cd "$(dirname "$0")"
xcodegen generate
pod install
xcodebuild -quiet \
  -workspace TesNavIOS.xcworkspace \
  -scheme TesNavIOS \
  -configuration Debug \
  -destination "id=${TESNAV_IOS_DEVICE_ID}" \
  -derivedDataPath DerivedData \
  -allowProvisioningUpdates \
  build
xcrun devicectl device install app \
  --device "${TESNAV_IOS_DEVICE_ID}" \
  DerivedData/Build/Products/Debug-iphoneos/TesNavIOS.app
