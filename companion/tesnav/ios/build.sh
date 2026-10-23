#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
xcodegen generate
pod install
xcodebuild -quiet \
  -workspace TesNavIOS.xcworkspace \
  -scheme TesNavIOS \
  -configuration Debug \
  -sdk iphonesimulator \
  -destination "generic/platform=iOS Simulator" \
  -derivedDataPath DerivedData \
  CODE_SIGNING_ALLOWED=NO \
  build
