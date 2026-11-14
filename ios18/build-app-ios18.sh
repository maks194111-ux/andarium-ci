#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Build the Andarium app for iOS 18 around the ANGLE runtime. Unsigned, and
# without the Android system image, which is added outside this public CI.
set -euo pipefail
UPSTREAM=$(cd "$1" && pwd)
WORK=$(cd "$2" && pwd)
ENGINE=$3
HERE=$(cd "$(dirname "$0")" && pwd)

cd "$UPSTREAM"
mkdir -p .build
tar -C .build -xzf "$ENGINE"
ls .build/kernarium-xcframeworks
python3 "$HERE/apply.py" "$UPSTREAM"
python3 "$HERE/app_patch.py" "$UPSTREAM"
python3 "$HERE/refresh_patch.py" "$UPSTREAM" app
# The bundle's system image directory: filled in when the IPA is assembled.
mkdir -p .build/andarium-system
echo "The Android system image is added when the IPA is assembled." > .build/andarium-system/PLACEHOLDER.txt

set +e
xcodebuild -project Andarium/Andarium.xcodeproj -scheme Andarium -configuration Release \
  -sdk iphoneos -destination 'generic/platform=iOS' -derivedDataPath "$WORK/app-build" \
  IPHONEOS_DEPLOYMENT_TARGET=18.0 CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY= build > "$WORK/xcodebuild.log" 2>&1
status=$?
set -e
grep -E "error:|error :|BUILD (SUCCEEDED|FAILED)|Undefined symbol|ld: " "$WORK/xcodebuild.log" | sort -u | head -150 || true
if [ "$status" -ne 0 ]; then
  tail -40 "$WORK/xcodebuild.log"
  exit "$status"
fi

APP="$WORK/app-build/Build/Products/Release-iphoneos/Andarium.app"
ls -la "$APP" "$APP/Frameworks"
plutil -p "$APP/Info.plist" | grep -E 'MinimumOSVersion|CFBundleIdentifier|CFBundleVersion|UIRequiredDeviceCapabilities' -A2
xcrun vtool -show-build "$APP/Andarium" | grep -E 'platform|minos'
# The entitlements the app must be signed with, kept beside it for the signer.
cp Andarium/Config/Andarium.entitlements "$WORK/Andarium.entitlements"
# Ad-hoc signature that carries the entitlements, as upstream's released IPA
# does, so a sideloading tool can keep them when it signs for the owner.
/usr/libexec/PlistBuddy -c "Add :get-task-allow bool true" "$WORK/Andarium.entitlements"
for framework in "$APP"/Frameworks/*.framework; do
  codesign --force --sign - "$framework"
done
codesign --force --sign - --entitlements "$WORK/Andarium.entitlements" "$APP"
codesign -d --entitlements - "$APP" 2>&1 | grep -E 'key|true' || true
rm -rf "$WORK/Payload"; mkdir "$WORK/Payload"
cp -R "$APP" "$WORK/Payload/"
(cd "$WORK" && zip -qry Andarium-ios18-no-image.zip Payload Andarium.entitlements)
ls -la "$WORK/Andarium-ios18-no-image.zip"
echo "Unsigned app for iOS 18 built. It carries no Android system image and has not run on a device."
