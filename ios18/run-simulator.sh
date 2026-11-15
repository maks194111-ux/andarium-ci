#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Run the iOS 18 device build of Andarium on an "iPhone 11, iOS 18" Simulator
# on the CI Mac and collect screenshots and logs.
#
# The app and its frameworks are the device binaries, with only the platform
# tag in each file changed to "iOS Simulator" so the Simulator loads them. The
# code is therefore the code the phone gets (the device branches, the device
# ANGLE build). What this does NOT show: the phone's memory limit, its speed,
# its GPU driver, or signing. Android comes from upstream's public release.
set -uo pipefail
APPZIP=$1
WORK=$(cd "$2" && pwd)
OUT="$WORK/simulator-report"; mkdir -p "$OUT"
SECONDS_TO_WATCH=${3:-420}
# Optional: ANGLE built for the Simulator. The device build of ANGLE asks the
# GPU for a feature family the Simulator never reports and then offers no
# OpenGL ES 3; a real A13 reports it. Everything else stays the device code.
ANGLE_SIM=${4:-}
stage() { echo; echo "===== STAGE: $* ====="; }

stage "host"
sw_vers; sysctl -n hw.ncpu hw.memsize; xcodebuild -version

stage "app with the public Android image"
mkdir -p "$WORK/app" && cd "$WORK/app"
unzip -qo "$APPZIP"
APP="$WORK/app/Payload/Andarium.app"
curl -fsSL --retry 3 -o "$WORK/upstream.ipa" \
  https://github.com/imxieyi/Kernarium/releases/download/1.0b9-beta/Andarium-1.0-9.ipa
rm -rf "$APP/andarium-system"
(cd "$WORK" && unzip -qo upstream.ipa 'Payload/Andarium.app/andarium-system/*' -d upstream-ipa)
mv "$WORK/upstream-ipa/Payload/Andarium.app/andarium-system" "$APP/andarium-system"
rm -rf "$WORK/upstream.ipa" "$WORK/upstream-ipa"
ls -la "$APP/andarium-system" "$APP/andarium-system/guest"

if [ -n "$ANGLE_SIM" ]; then
  stage "graphics library: the Simulator build of the same ANGLE sources"
  for framework in libEGL libGLESv2; do
    rm -rf "$APP/Frameworks/$framework.framework"
    cp -R "$ANGLE_SIM/iossim/$framework.framework" "$APP/Frameworks/"
    xcrun vtool -show-build "$APP/Frameworks/$framework.framework/$framework" | grep -E 'platform|minos' | tr -s ' \n' ' '; echo
  done
fi

stage "retag the device binaries for the Simulator"
SDKV=$(xcrun --sdk iphonesimulator --show-sdk-version)
for binary in "$APP/Andarium" "$APP"/Frameworks/*.framework/*; do
  file "$binary" | grep -q Mach-O || continue
  if xcrun vtool -show-build "$binary" | grep -q IOSSIMULATOR; then echo "$(basename "$binary"): already a Simulator binary"; continue; fi
  xcrun vtool -set-build-version iossim 18.0 "$SDKV" -replace -output "$binary.sim" "$binary" || exit 1
  mv "$binary.sim" "$binary"
  echo "$(basename "$binary"): $(xcrun vtool -show-build "$binary" | grep -E 'platform|minos' | tr -s ' \n' ' ')"
done
/usr/libexec/PlistBuddy -c "Delete :CFBundleSupportedPlatforms" "$APP/Info.plist" || true
/usr/libexec/PlistBuddy -c "Add :CFBundleSupportedPlatforms array" -c "Add :CFBundleSupportedPlatforms:0 string iPhoneSimulator" "$APP/Info.plist"
/usr/libexec/PlistBuddy -c "Set :DTPlatformName iphonesimulator" "$APP/Info.plist" || true
/usr/libexec/PlistBuddy -c "Delete :UIRequiredDeviceCapabilities" "$APP/Info.plist" || true
BUNDLE=$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$APP/Info.plist")
for framework in "$APP"/Frameworks/*.framework; do codesign --force --sign - "$framework" || exit 1; done
codesign --force --sign - "$APP" || exit 1

stage "iPhone 11 on iOS 18"
xcrun simctl list runtimes
RUNTIME=$(xcrun simctl list runtimes | grep -o "com.apple.CoreSimulator.SimRuntime.iOS-18-[0-9]*" | sort -V | tail -1)
[ -n "$RUNTIME" ] || { echo "no iOS 18 runtime on this Mac"; exit 1; }
UDID=$(xcrun simctl create "Andarium iPhone 11" com.apple.CoreSimulator.SimDeviceType.iPhone-11 "$RUNTIME") || exit 1
xcrun simctl boot "$UDID" || exit 1
xcrun simctl bootstatus "$UDID" -b | tail -2
echo "device: iPhone 11, runtime $RUNTIME, bundle $BUNDLE"
xcrun simctl install "$UDID" "$APP" || { echo "INSTALL FAILED"; exit 1; }

shot() { xcrun simctl io "$UDID" screenshot "$OUT/$1.png" >/dev/null 2>&1 && echo "screenshot $1"; }
crashes() { find ~/Library/Logs/DiagnosticReports -name 'Andarium*' -newer "$WORK/app" 2>/dev/null; }
alive() { xcrun simctl spawn "$UDID" launchctl list 2>/dev/null | grep -q "$BUNDLE"; }

stage "launch 1: as a person would (Home screen)"
xcrun simctl launch --console-pty "$UDID" "$BUNDLE" > "$OUT/console-home.txt" 2>&1 &
sleep 25; shot 01-home
alive && echo "RESULT home: app is running" || echo "RESULT home: app is NOT running"
xcrun simctl terminate "$UDID" "$BUNDLE" >/dev/null 2>&1; sleep 3
tail -30 "$OUT/console-home.txt"

stage "launch 2: start Android"
xcrun simctl spawn "$UDID" log stream --style compact --predicate 'process == "Andarium"' > "$OUT/oslog.txt" 2>&1 &
LOGPID=$!
SIMCTL_CHILD_ANDARIUM_START=normal SIMCTL_CHILD_ANDARIUM_STATS=1 \
  xcrun simctl launch --console-pty "$UDID" "$BUNDLE" > "$OUT/console-start.txt" 2>&1 &
elapsed=0; index=2
while [ "$elapsed" -lt "$SECONDS_TO_WATCH" ]; do
  sleep 30; elapsed=$((elapsed + 30))
  shot "$(printf '%02d' "$index")-start-${elapsed}s"; index=$((index + 1))
  echo "t=${elapsed}s console lines=$(wc -l < "$OUT/console-start.txt" | tr -d ' ') last stats: $(grep 'Andarium stats' "$OUT/console-start.txt" | tail -1)"
  if ! alive; then echo "RESULT start: app ended at about ${elapsed}s"; break; fi
done
alive && echo "RESULT start: app still running after ${elapsed}s"
kill "$LOGPID" 2>/dev/null

stage "what the app printed"
grep -c . "$OUT/console-start.txt"
grep -iE "error|fail|fatal|panic|abort|refus|cannot|unsupported|jetsam|memory|EGL|ANGLE|Metal|GLES|renderer|returned|Andarium:" "$OUT/console-start.txt" | cut -c1-260 | sort | uniq -c | sort -rn | head -80
echo "--- first 60 lines"; head -60 "$OUT/console-start.txt" | cut -c1-260
echo "--- last 60 lines"; tail -60 "$OUT/console-start.txt" | cut -c1-260
echo "--- statistics lines"; grep 'Andarium stats' "$OUT/console-start.txt" | tail -15

stage "crash reports"
sleep 10
for report in $(crashes); do
  cp "$report" "$OUT/"; echo "CRASH REPORT $(basename "$report")"
  python3 - "$report" <<'PY'
import json, sys
text = open(sys.argv[1]).read()
try:
    head, body = text.split("\n", 1)
    data = json.loads(body)
    print("exception:", data.get("exception"))
    print("termination:", data.get("termination"))
    print("asi:", data.get("asi"))
    images = data.get("usedImages", [])
    for thread in data.get("threads", []):
        if thread.get("triggered"):
            for frame in thread.get("frames", [])[:25]:
                image = images[frame["imageIndex"]].get("name", "?") if frame.get("imageIndex", -1) < len(images) else "?"
                print("  ", image, frame.get("symbol", hex(frame.get("imageOffset", 0))))
except Exception as error:
    print("unparsed report:", error); print(text[:3000])
PY
done
[ -z "$(crashes)" ] && echo "no crash report"
xcrun simctl shutdown "$UDID" >/dev/null 2>&1
ls -la "$OUT"
