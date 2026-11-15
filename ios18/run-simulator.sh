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
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(cd "$2" && pwd)
OUT="$WORK/simulator-report"; mkdir -p "$OUT"
SECONDS_TO_WATCH=${3:-420}
# Optional: ANGLE built for the Simulator. The device build of ANGLE asks the
# GPU for a feature family the Simulator never reports and then offers no
# OpenGL ES 3; a real A13 reports it. Everything else stays the device code.
ANGLE_SIM=${4:-}
# Optional: guest RAM in MiB, to start Android at the size a 4 GB phone gets.
MEMORY_MIB=${5:-}
# Optional: Simulator device type and iOS major version, to cover other models.
DEVICE_TYPE=${6:-iPhone-11}
IOS_MAJOR=${7:-18}
stage() { echo; echo "===== STAGE: $* ====="; }

stage "host"
sw_vers; sysctl -n hw.ncpu hw.memsize; xcodebuild -version

stage "verify exact runtime and device before downloading the image"
selection=$(python3 "$HERE/simulator_check.py" select "$OUT" --major "$IOS_MAJOR" --device "$DEVICE_TYPE")
selection_status=$?
if [ "$selection_status" != 0 ]; then
  echo "RESULT: $selection"
  exit "$selection_status"
fi
read -r RUNTIME DEVICE_IDENTIFIER <<< "$selection"
echo "Selected $DEVICE_IDENTIFIER on $RUNTIME"

stage "app and Android image"
mkdir -p "$WORK/app" && cd "$WORK/app"
unzip -qo "$APPZIP" || exit 1
APP="$WORK/app/Payload/Andarium.app"
if [ "${IMAGE_KIND:-stock}" = gapps ]; then
  [ -n "${GAPPS_IPA_URL:-}" ] || { echo "RESULT: Google image URL not configured"; exit 1; }
  echo "Using the Google image from the supplied phone IPA, not the stock image."
  curl -fsSL --retry 3 -o "$WORK/upstream.ipa" "$GAPPS_IPA_URL" 2>/dev/null || { echo "RESULT: Google image download failed"; exit 1; }
else
curl -fsSL --retry 3 -o "$WORK/upstream.ipa" \
  https://github.com/imxieyi/Kernarium/releases/download/1.0b9-beta/Andarium-1.0-9.ipa || exit 1
fi
rm -rf "$APP/andarium-system"
(cd "$WORK" && unzip -qo upstream.ipa 'Payload/Andarium.app/andarium-system/*' -d upstream-ipa) || exit 1
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
# No entitlements: the Mac refuses an ad-hoc signature that carries identifier
# entitlements ("Taskgated Invalid Signature"). The cost is that the Simulator
# keychain refuses the adb key, so the app's adb features do not work here.
codesign --force --sign - "$APP" || exit 1

stage "$DEVICE_TYPE on iOS $IOS_MAJOR"
UDID=$(xcrun simctl create "Andarium $DEVICE_TYPE" "$DEVICE_IDENTIFIER" "$RUNTIME") || { echo "RESULT: $DEVICE_TYPE cannot be created on $RUNTIME"; exit 1; }
xcrun simctl boot "$UDID" || exit 1
xcrun simctl bootstatus "$UDID" -b | tail -2
echo "device: $DEVICE_TYPE, runtime $RUNTIME, bundle $BUNDLE"
xcrun simctl install "$UDID" "$APP" || { echo "INSTALL FAILED"; exit 1; }

shot() { xcrun simctl io "$UDID" screenshot "$OUT/$1.png" >/dev/null 2>&1 && echo "screenshot $1"; }
crashes() { find ~/Library/Logs/DiagnosticReports -name 'Andarium*' -newer "$WORK/app" 2>/dev/null; }
alive() { pgrep -f "Andarium.app/Andarium" >/dev/null; }

stage "launch 1: as a person would (Home screen)"
xcrun simctl launch --console-pty "$UDID" "$BUNDLE" > "$OUT/console-home.txt" 2>&1 &
sleep 25; shot 01-home
alive && echo "RESULT home: app is running" || echo "RESULT home: app is NOT running"
xcrun simctl terminate "$UDID" "$BUNDLE" >/dev/null 2>&1; sleep 3
tail -30 "$OUT/console-home.txt"

stage "launch 2: start Android"
xcrun simctl spawn "$UDID" log stream --style compact --predicate 'process == "Andarium"' > "$OUT/oslog.txt" 2>&1 &
LOGPID=$!
[ -n "$MEMORY_MIB" ] && export SIMCTL_CHILD_KERNARIUM_GUEST_MEMORY_MIB="$MEMORY_MIB" && echo "guest RAM stated: $MEMORY_MIB MiB"
SIMCTL_CHILD_ANDARIUM_START=normal SIMCTL_CHILD_ANDARIUM_STATS=1 \
  xcrun simctl launch --console-pty "$UDID" "$BUNDLE" > "$OUT/console-start.txt" 2>&1 &
began=$(date +%s); elapsed=0; index=2
while [ "$elapsed" -lt "$SECONDS_TO_WATCH" ]; do
  sleep 25; elapsed=$(( $(date +%s) - began ))
  shot "$(printf '%02d' "$index")-start-${elapsed}s"; index=$((index + 1))
  echo "t=${elapsed}s console lines=$(wc -l < "$OUT/console-start.txt" | tr -d ' ') last stats: $(grep 'Andarium stats' "$OUT/console-start.txt" | tail -1)"
  grep -a 'Andarium: boot reached' "$OUT/console-start.txt" | tail -1
  if ! alive; then echo "RESULT start: app ended at about ${elapsed}s"; ENDED=1; break; fi
  if grep -aq 'Andarium: runtime returned' "$OUT/console-start.txt"; then
    echo "RESULT start: the guest runtime returned at about ${elapsed}s"
    ENDED=1
    break
  fi
done
[ -z "${ENDED:-}" ] && echo "RESULT start: app still running after ${elapsed}s"
echo "SUMMARY $DEVICE_TYPE iOS $IOS_MAJOR ($RUNTIME): window=$(grep -ac 'UML: cannot reserve' "$OUT/console-start.txt") refusals, kernel=$(grep -ac 'boot reached kernelRunning\|boot reached androidStarting' "$OUT/console-start.txt"), screen=$(grep -ac 'boot reached screenStarting' "$OUT/console-start.txt"), first-frame=$(grep -ac 'first frame copied' "$OUT/console-start.txt"), ready=$(grep -ac 'boot reached ready' "$OUT/console-start.txt"), stopped=$(grep -ac 'runtime returned' "$OUT/console-start.txt")"
host_memory() { vm_stat | awk '/Pages free|Pages inactive|Pages wired|Pages occupied by compressor|Swapouts/ {printf "%s %s; ", $0, ""}'; echo; }
echo "host memory: $(host_memory)"; sysctl -n vm.swapusage
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
ALIVE=no; alive && ALIVE=yes
python3 "$HERE/simulator_check.py" result "$OUT" --alive "$ALIVE"
RESULT=$?
xcrun simctl shutdown "$UDID" >/dev/null 2>&1
ls -la "$OUT"
exit "$RESULT"
