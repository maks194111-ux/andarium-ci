#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# The original Andarium (iOS 27, Metal 4, upstream's own graphics stack) built
# from source with one change: the guest display follows the host screen's
# refresh rate instead of a fixed 60 Hz. Everything else is upstream's flow
# (Andarium/README.md, "Build"). Unsigned app without the Android system image.
set -euo pipefail
UPSTREAM=$(cd "$1" && pwd)
WORK=$(cd "$2" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
stage() { echo; echo "===== STAGE: $* ====="; }

mkdir -p "$WORK/tools"
printf '#!/bin/sh\nexec python3 -m mesonbuild.mesonmain "$@"\n' > "$WORK/tools/meson"
chmod +x "$WORK/tools/meson"
export PATH="$WORK/tools:$PATH"
for tool in autoconf automake libtool pkg-config ninja cmake bison flex groff; do
  HOMEBREW_NO_AUTO_UPDATE=1 brew list "$tool" >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install "$tool"
done
export PATH="$(brew --prefix bison)/bin:$(brew --prefix flex)/bin:$PATH"

cd "$UPSTREAM"
stage "refresh-rate change"
python3 "$HERE/../ios18/refresh_patch.py" "$UPSTREAM" engine
python3 "$HERE/../ios18/refresh_patch.py" "$UPSTREAM" app

stage "upstream GPU stack for the device (Mesa Zink, KosmicKrisp, virglrenderer)"
bash dependencies/prepare.sh --product apple-gpu-vulkan-experiment
bash dependencies/build-apple-gpu.sh --platform ios

stage "network and compression dependencies"
bash dependencies/prepare.sh --product ios-network
bash dependencies/build-ios-network.sh --platform ios
bash dependencies/prepare.sh --product ios-compression
bash dependencies/build-ios-zstd.sh

stage "accepted Android kernel bundle from the upstream release"
mkdir -p .build/kernel/artifacts
curl -fsSL --retry 3 -o "$WORK/kernel.tar.gz" \
  https://github.com/imxieyi/Kernarium/releases/download/1.0b9-beta/android-6.18-arm64-4k-20261111-6.18.60-mc2.tar.gz
tar -C .build/kernel/artifacts -xzf "$WORK/kernel.tar.gz"

stage "device Android runtime"
cmake --preset kernarium-ios-device-android
cmake --build --preset kernarium-ios-device-android

stage "package frameworks"
sh Kernarium/scripts/package-ios-frameworks.sh --runtimes android
du -sh .build/kernarium-xcframeworks/*

stage "application"
mkdir -p .build/andarium-system
echo "The Android system image is added when the IPA is assembled." > .build/andarium-system/PLACEHOLDER.txt
set +e
xcodebuild -project Andarium/Andarium.xcodeproj -scheme Andarium -configuration Release \
  -sdk iphoneos -destination 'generic/platform=iOS' -derivedDataPath "$WORK/app-build" \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= build > "$WORK/xcodebuild.log" 2>&1
status=$?
set -e
grep -E "error:|error :|BUILD (SUCCEEDED|FAILED)|Undefined symbol|ld: " "$WORK/xcodebuild.log" | sort -u | head -150 || true
if [ "$status" -ne 0 ]; then tail -40 "$WORK/xcodebuild.log"; exit "$status"; fi

APP="$WORK/app-build/Build/Products/Release-iphoneos/Andarium.app"
ls -la "$APP" "$APP/Frameworks"
plutil -p "$APP/Info.plist" | grep -E 'MinimumOSVersion|CFBundleIdentifier|CADisableMinimumFrameDurationOnPhone' -A1
cp Andarium/Config/Andarium.entitlements "$WORK/Andarium.entitlements"
/usr/libexec/PlistBuddy -c "Add :get-task-allow bool true" "$WORK/Andarium.entitlements"
for framework in "$APP"/Frameworks/*.framework; do codesign --force --sign - "$framework"; done
codesign --force --sign - --entitlements "$WORK/Andarium.entitlements" "$APP"
rm -rf "$WORK/Payload"; mkdir "$WORK/Payload"
cp -R "$APP" "$WORK/Payload/"
(cd "$WORK" && zip -qry Andarium-ios27-smooth-no-image.zip Payload Andarium.entitlements)
ls -la "$WORK/Andarium-ios27-smooth-no-image.zip"
echo "App for iOS 27 with the refresh-rate change built. No system image inside; not run on a device."
