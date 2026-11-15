#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Boot test: upstream's macOS Android executable on the ANGLE path (the same
# Virgl-only renderer the iOS 18 app carries), headless, on the CI Mac.
# It answers "does Android start on OpenGL ES 3.0 without Vulkan" and collects
# the guest's graphics state. It says nothing about speed on a phone.
set -euo pipefail
UPSTREAM=$(cd "$1" && pwd)
WORK=$(cd "$2" && pwd)
ANGLE=$(cd "$3" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$WORK/boot-report"; mkdir -p "$OUT"
stage() { echo; echo "===== STAGE: $* ====="; }

sw_vers; sysctl -n hw.ncpu hw.memsize
HOST_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
mkdir -p "$WORK/tools"
printf '#!/bin/sh\nexec python3 -m mesonbuild.mesonmain "$@"\n' > "$WORK/tools/meson"
chmod +x "$WORK/tools/meson"
export PATH="$WORK/tools:$PATH"
for tool in autoconf automake libtool pkg-config ninja cmake gptfdisk groff; do
  HOMEBREW_NO_AUTO_UPDATE=1 brew list "$tool" >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install "$tool"
done
command -v adb >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install --cask android-platform-tools
adb version | head -1; command -v sgdisk

cd "$UPSTREAM"
stage "retarget build system (macOS product, ANGLE host GL)"
python3 "$HERE/engine_build_patch.py" "$UPSTREAM" macos
python3 "$HERE/angle_provider.py" "$UPSTREAM"
python3 "$HERE/refresh_patch.py" "$UPSTREAM" engine
python3 "$HERE/angle_scanout.py" "$UPSTREAM"
python3 "$HERE/qos_patch.py" "$UPSTREAM" engine
python3 "$HERE/tier_patch.py" "$UPSTREAM"
# The launcher script passes the tier threshold named in UML_JIT_TIER.
python3 - <<'PY3'
from pathlib import Path
path = Path("tools/boot_android.py")
text = path.read_text()
old = '        f"--execution-engine={options.engine}",\n'
if text.count(old) != 1:
    raise SystemExit("launcher engine argument not found")
path.write_text(text.replace(old, old + '        *([f"--jit-tier={os.environ[\'UML_JIT_TIER\']}"] if os.environ.get("UML_JIT_TIER") else []),\n'))
PY3
# The CI Mac is a virtual machine without a hardware video encoder, and the
# launcher treats the missing encoder as fatal. The test boots without that
# device; it is unrelated to the graphics path under test.
python3 - <<'PY2'
from pathlib import Path
path = Path("darwin/app/macos/main.cpp")
text = path.read_text()
old = "if (prepared_.video_encoder && !information_only_ &&"
if text.count(old) != 1:
    raise SystemExit("video encoder start not found")
path.write_text(text.replace(old, "if (false && prepared_.video_encoder && !information_only_ &&"))
PY2
if [ "$HOST_MAJOR" -lt 27 ]; then
  echo "host is macOS $HOST_MAJOR: lowering the macOS floor from 27.0 for this test"
  FLOOR="$HOST_MAJOR.0"
  sed -i '' "s/set(_uml_apple_deployment_target 27.0)/set(_uml_apple_deployment_target $FLOOR)/" cmake/toolchains/Apple.cmake
  sed -i '' "s/^DEPLOYMENT_TARGET=27.0/DEPLOYMENT_TARGET=$FLOOR/" dependencies/build.sh
  grep -rl '27\.0' dependencies/cmake dependencies/platforms | xargs sed -i '' "s/27\.0/$FLOOR/g"
else
  FLOOR=27.0
fi

stage "GPU prefix for macOS: libepoxy and virglrenderer on ANGLE"
bash dependencies/prepare.sh --product apple-gpu-vulkan-experiment
SOURCES="$UPSTREAM/external/sources"
PREFIX="$UPSTREAM/.build/dependencies/apple-gpu-vulkan-experiment/macos-arm64"
BUILD="$WORK/gpu-macos-build"
rm -rf "$PREFIX" "$BUILD"; mkdir -p "$PREFIX/include/GL" "$PREFIX/lib/pkgconfig" "$PREFIX/Frameworks" "$BUILD"
python3 - "$SOURCES/libepoxy/src/dispatch_common.c" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
old = '#define EGL_LIB "@rpath/MesaEGL.framework/MesaEGL"'
if text.count(old) != 1:
    raise SystemExit("libepoxy provider line not found")
path.write_text(text.replace(old, '#define EGL_LIB "@rpath/libEGL.framework/libEGL"'))
PY
(
  export PKG_CONFIG_PATH= PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
  export SDKROOT="$(xcrun --sdk macosx --show-sdk-path)" MACOSX_DEPLOYMENT_TARGET="$FLOOR"
  export CC="$(xcrun --find clang)" CXX="$(xcrun --find clang++)"; export OBJC="$CC" OBJCXX="$CXX"
  meson setup "$BUILD/epoxy" "$SOURCES/libepoxy" --prefix "$PREFIX" --libdir lib \
    --buildtype release --wrap-mode=nodownload -Dc_args="-I$ANGLE/include" \
    -Ddefault_library=static -Dtests=false -Dglx=no -Degl=yes -Dx11=false
  meson compile -C "$BUILD/epoxy" -j 3
  meson install -C "$BUILD/epoxy"
  MESA="$SOURCES/mesa"; [ -d "$MESA" ] || MESA="$SOURCES/Mesa"
  install -m 0644 "$MESA/src/gallium/drivers/zink/zink_interop_public.h" "$PREFIX/include/GL/"
  install -m 0644 "$MESA/include/GL/mesa_glinterop.h" "$PREFIX/include/GL/"
  meson setup "$BUILD/virgl" "$SOURCES/virglrenderer" --prefix "$PREFIX" --libdir lib \
    --buildtype release --wrap-mode=nodownload -Dc_args="-I$ANGLE/include -I$PREFIX/include" \
    -Ddefault_library=static -Dtests=false -Dcheck-gl-errors=false -Dvideo=false \
    -Dplatforms=egl -Dvenus=false
  meson compile -C "$BUILD/virgl" -j 3
  meson install -C "$BUILD/virgl"
)
install -m 0644 "$SOURCES/virglrenderer/src/virgl_hw.h" "$PREFIX/include/virgl/virgl_hw.h"
rm -rf "$PREFIX/lib/pkgconfig" "$PREFIX/bin" "$PREFIX/include/GL/zink_interop_public.h"
cp -R "$ANGLE/include/EGL" "$ANGLE/include/KHR" "$PREFIX/include/"
# ANGLE's macOS dylibs, given the framework names the build system links.
OLD_GLES=$(otool -L "$ANGLE/macos/libEGL.dylib" | awk '/libGLESv2/ {print $1}')
for name in libEGL libGLESv2; do
  mkdir -p "$PREFIX/Frameworks/$name.framework"
  cp "$ANGLE/macos/$name.dylib" "$PREFIX/Frameworks/$name.framework/$name"
  install_name_tool -id "@rpath/$name.framework/$name" "$PREFIX/Frameworks/$name.framework/$name"
  cat > "$PREFIX/Frameworks/$name.framework/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>$name</string>
<key>CFBundleIdentifier</key><string>org.chromium.angle.$name</string>
<key>CFBundlePackageType</key><string>FMWK</string>
<key>CFBundleVersion</key><string>1</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
</dict></plist>
PLIST
done
[ -z "$OLD_GLES" ] || install_name_tool -change "$OLD_GLES" @rpath/libGLESv2.framework/libGLESv2 \
  "$PREFIX/Frameworks/libEGL.framework/libEGL"
for name in libEGL libGLESv2; do
  codesign --force --sign - "$PREFIX/Frameworks/$name.framework/$name"
  otool -L "$PREFIX/Frameworks/$name.framework/$name" | head -4
done

stage "macOS host libraries"
bash dependencies/prepare.sh --product macos
bash dependencies/build.sh

stage "accepted Android kernel bundle and release from upstream"
mkdir -p .build/kernel/artifacts .build/android/releases
curl -fsSL --retry 3 -o "$WORK/kernel.tar.gz" \
  https://github.com/imxieyi/Kernarium/releases/download/1.0b9-beta/android-6.18-arm64-4k-20261111-6.18.60-mc2.tar.gz
tar -C .build/kernel/artifacts -xzf "$WORK/kernel.tar.gz"
curl -fsSL --retry 3 -o "$WORK/release.tar.gz" \
  https://github.com/imxieyi/Kernarium/releases/download/1.0b9-beta/lineage24-mainline6.18-4k-20261110-los24-r22.tar.gz
tar -C .build/android/releases -xzf "$WORK/release.tar.gz"
rm -f "$WORK/release.tar.gz"
ls -la .build/android/releases/*

stage "configure and build the macOS Android executable"
# Upstream's closure check admits only its own Mesa frameworks; this test binary
# links ANGLE's instead, so the check is replaced and that is stated here.
printf '#!/bin/sh\necho "runtime closure check not run: ANGLE test binary"\n' > dependencies/verify-runtime-dependencies.sh
cmake --preset macos-android17
cmake --build .build/presets/macos-android17 --target uml-darwin-android17 -j 4 -- -k 0
EMULATOR=$(find .build/presets/macos-android17 -name uml-darwin-android17 -type f | head -1)
otool -L "$EMULATOR" | grep -E 'EGL|GLES' || true
# ANGLE's macOS libEGL opens "libGLESv2.dylib" beside itself.
ln -sf ../libGLESv2.framework/libGLESv2 "$(dirname "$EMULATOR")/Frameworks/libEGL.framework/libGLESv2.dylib"
ls -la "$(dirname "$EMULATOR")/Frameworks/libEGL.framework"

stage "boot Android headless on ANGLE"
CPUS=$(sysctl -n hw.ncpu)
SERIAL=127.0.0.1:5555
# The launcher drops its own ADB session when it has seen the boot; reconnect
# before every query.
guest() { adb connect "$SERIAL" >/dev/null 2>&1; adb -s "$SERIAL" "$@"; }
export UML_ANGLE_SCANOUT_STATS=1
RESULT=0

# One measured run. Arguments: name, guest RAM, refresh rate, process memory
# limit in MiB (0 for none), width, height, density.
# The limit makes the Mac run size its budgets as a device with that limit
# does and write a "virtual Jetsam" line when the footprint passes it.
profile() {
  local name=$1 memory=$2 hertz=$3 limit=$4 width=$5 height=$6 dpi=$7 engine=${8:-gadgets}
  local dir="$OUT/$name"; mkdir -p "$dir"
  stage "profile $name: RAM $memory, $hertz Hz, limit ${limit} MiB, ${width}x${height}"
  export UML_GUEST_REFRESH_HZ=$hertz
  if [ "$limit" != 0 ]; then export UML_MEMORY_LIMIT_MIB=$limit; else unset UML_MEMORY_LIMIT_MIB; fi
  local started=$(date +%s)
  python3 tools/boot_android.py --instance "$WORK/instance-$name" --reset --provision --emulator "$EMULATOR" \
    --display offscreen --width "$width" --height "$height" --dpi "$dpi" --audio-output null \
    --cpus "$CPUS" --memory "$memory" --engine "$engine" --adb-timeout 1800 --boot-timeout 3000 \
    > "$dir/launcher.log" 2>&1 &
  local launcher=$!
  local booted=0 i state
  for i in $(seq 1 300); do
    sleep 10
    kill -0 "$launcher" 2>/dev/null || { echo "launcher exited"; break; }
    state=$(guest shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
    if [ "$state" = 1 ]; then booted=1; echo "$name: boot_completed after about $(( $(date +%s) - started )) s"; break; fi
  done
  if [ "$booted" = 1 ]; then
    # Let the launcher finish provisioning and the first-boot work settle.
    for i in $(seq 1 30); do
      [ "$(guest shell settings get secure user_setup_complete 2>/dev/null | tr -d '\r')" = 1 ] && break
      sleep 5
    done
    sleep 60
    guest shell 'dumpsys SurfaceFlinger' > "$dir/surfaceflinger.txt" 2>&1
    grep -E "renderRate|activeMode" "$dir/surfaceflinger.txt" | head -3
    local x=$((width / 2)) low=$((height * 3 / 4)) high=$((height / 4))
    guest shell "input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; am start -W -a android.settings.SETTINGS" > "$dir/start.txt" 2>&1
    sleep 20
    guest exec-out screencap -p > "$dir/settings.png"
    # 1. Scrolling the Settings list: sixteen slow drags.
    guest shell "dumpsys gfxinfo com.android.settings reset >/dev/null; dumpsys SurfaceFlinger --timestats -clear -enable"
    guest shell "for n in 1 2 3 4 5 6 7 8; do input swipe $x $low $x $high 1200; input swipe $x $high $x $low 1200; done"
    guest shell "dumpsys SurfaceFlinger --timestats -dump -maxlayers 6" > "$dir/timestats-scroll.txt" 2>&1
    guest shell "dumpsys gfxinfo com.android.settings" > "$dir/gfxinfo-settings.txt" 2>&1
    guest shell "dumpsys gfxinfo com.android.settings framestats" > "$dir/framestats-settings.txt" 2>&1
    # 2. System animations: the notification shade, six times down and up.
    guest shell "dumpsys gfxinfo com.android.systemui reset >/dev/null; dumpsys SurfaceFlinger --timestats -clear"
    guest shell "for n in 1 2 3 4 5 6; do cmd statusbar expand-notifications; sleep 1.5; cmd statusbar collapse; sleep 1.5; done"
    guest shell "dumpsys SurfaceFlinger --timestats -dump -maxlayers 6" > "$dir/timestats-shade.txt" 2>&1
    guest shell "dumpsys gfxinfo com.android.systemui" > "$dir/gfxinfo-systemui.txt" 2>&1
    guest shell "dumpsys gfxinfo com.android.systemui framestats" > "$dir/framestats-systemui.txt" 2>&1
    guest shell "dumpsys SurfaceFlinger --timestats -disable"
    guest exec-out screencap -p > "$dir/after.png"
    guest shell "cat /proc/meminfo | head -20; cat /proc/swaps; cat /proc/pressure/memory" > "$dir/guest-memory.txt" 2>&1
    for part in scroll shade; do
      echo "--- $name / $part: display statistics"
      grep -E "^(totalFrames|missedFrames|clientCompositionFrames|displayOnTime|statsStart|statsEnd)|averageFPS|layerName|totalTimelineFrames|jankyFrames|sfLongCpuJankyFrames|sfLongGpuJankyFrames|appDeadlineMissedJankyFrames" \
        "$dir/timestats-$part.txt" | cut -c1-160 | head -40
    done
    for package in settings systemui; do
      echo "--- $name / $package: application frames"
      grep -E "Total frames rendered|Janky frames|percentile|Number Missed Vsync|Number Slow UI|Number Frame deadline" "$dir/gfxinfo-$package.txt" | head -16
    done
    for package in settings systemui; do
      python3 "$HERE/framestats.py" "$name / $package" "$dir/framestats-$package.txt" || true
    done
    # 3. Where the frame's time is: processor time per thread, then the render
    #    thread's system calls with their durations, both during a scroll.
    guest shell "am start -W -a android.settings.SETTINGS" >/dev/null 2>&1; sleep 5
    cat > "$dir/threads.sh" <<'GUEST'
for name in com.android.settings surfaceflinger; do
  for pid in $(pidof $name); do
    for task in /proc/$pid/task/*; do
      echo "$name $(cat $task/comm)|${task##*/} $(cat $task/schedstat)"
    done
  done
done
for pid in $(pgrep -f 'composer|allocator|kworker|virtio'); do
  echo "other $(cat /proc/$pid/comm)|$pid $(cat /proc/$pid/schedstat)"
done
GUEST
    guest push "$dir/threads.sh" /data/local/tmp/threads.sh >/dev/null 2>&1
    guest shell "dumpsys gfxinfo com.android.settings reset >/dev/null"
    guest shell "sh /data/local/tmp/threads.sh" > "$dir/threads-before.txt" 2>&1
    local split_start=$(date +%s)
    guest shell "for n in 1 2 3 4 5 6; do input swipe $x $low $x $high 1200; input swipe $x $high $x $low 1200; done"
    local split_seconds=$(( $(date +%s) - split_start ))
    guest shell "sh /data/local/tmp/threads.sh" > "$dir/threads-after.txt" 2>&1
    local split_frames=$(guest shell "dumpsys gfxinfo com.android.settings" | tr -d '\r' | awk '/Total frames rendered/ {print $4}')
    python3 "$HERE/split.py" "$name baseline" "$dir/threads-before.txt" "$dir/threads-after.txt" "${split_frames:-0}" "$split_seconds" || true
    # 4. The same scroll with settings of the guest's graphics driver that move
    #    or remove processor work without changing what is drawn.
    variant() {
      local tag=$1; shift
      local setting
      for setting in "$@"; do guest shell "setprop ${setting%%=*} ${setting#*=}"; done
      guest shell "am force-stop com.android.settings; am start -W -a android.settings.SETTINGS" >/dev/null 2>&1; sleep 8
      guest shell "input swipe $x $low $x $high 600; input swipe $x $high $x $low 600"; sleep 2
      guest shell "dumpsys gfxinfo com.android.settings reset >/dev/null"
      guest shell "sh /data/local/tmp/threads.sh" > "$dir/threads-$tag-before.txt" 2>&1
      local began=$(date +%s)
      guest shell "for n in 1 2 3 4 5 6; do input swipe $x $low $x $high 1200; input swipe $x $high $x $low 1200; done"
      local took=$(( $(date +%s) - began ))
      guest shell "sh /data/local/tmp/threads.sh" > "$dir/threads-$tag-after.txt" 2>&1
      local count=$(guest shell "dumpsys gfxinfo com.android.settings" | tr -d '\r' | awk '/Total frames rendered/ {print $4}')
      guest shell "dumpsys gfxinfo com.android.settings framestats" > "$dir/framestats-$tag.txt" 2>&1
      guest exec-out screencap -p > "$dir/variant-$tag.png"
      echo "--- variant $tag: $* ; threads of the app: $(guest shell 'for t in /proc/$(pidof com.android.settings)/task/*; do cat $t/comm; done' | tr -d '\r' | grep -ciE 'gl|mesa') with gl in the name"
      python3 "$HERE/split.py" "$name $tag" "$dir/threads-$tag-before.txt" "$dir/threads-$tag-after.txt" "${count:-0}" "$took" || true
      python3 "$HERE/framestats.py" "$name $tag" "$dir/framestats-$tag.txt" || true
      for setting in "$@"; do guest shell "setprop ${setting%%=*} ''"; done
    }
    variant same
    variant again
    guest shell 'ls /vendor/lib64/egl /vendor/lib64/dri 2>/dev/null; getprop | grep -i mesa; strings /vendor/lib64/dri/*.so 2>/dev/null | grep -m3 -iE "^Mesa [0-9]|mesa [0-9]+\.[0-9]+\.[0-9]"' 2>&1 | head -30
    guest shell "top -b -n 1 -H -m 25 -o PID,TID,%CPU,CMD,NAME" > "$dir/guest-top.txt" 2>&1
    guest shell "getprop | grep -iE 'hwui|renderer|debug.sf|ro.surface_flinger|vsync|ro.hardware.egl|ro.opengles|zygote|dalvik.vm.usejit|dalvik.vm.dex2oat-filter|pm.dexopt'" > "$dir/guest-props.txt" 2>&1
    echo "--- $name: guest properties"; cut -c1-150 "$dir/guest-props.txt" | head -60
    echo "--- $name: guest memory"; grep -E "MemTotal|MemAvailable|SwapTotal|SwapFree|some|full" "$dir/guest-memory.txt"
    local pid=$(pgrep -f uml-darwin-android17 | head -1)
    echo "--- $name: host process"; [ -z "$pid" ] || top -l 1 -pid "$pid" -stats pid,mem,cpu,threads | tail -2
    guest logcat -d > "$dir/logcat.txt" 2>&1
    echo "$name: fatal entries in logcat: $(grep -ciE "FATAL EXCEPTION|Fatal signal" "$dir/logcat.txt")"
    grep -E "FATAL EXCEPTION|Fatal signal|lowmemorykiller|lmkd.*[Kk]ill" "$dir/logcat.txt" | cut -c1-200 | head -12
  else
    echo "RESULT: profile $name did not reach boot_completed"; RESULT=1
  fi
  kill -0 "$launcher" 2>/dev/null && echo "$name: emulator still running at the end" || { echo "$name: EMULATOR EXITED DURING THE TEST"; RESULT=1; }
  echo "--- $name: host lines"
  grep -E "virtual Jetsam|memory limit|GPU budget|short of|Darwin host fault" "$dir/launcher.log" | cut -c1-220 | sort | uniq -c | head -12
  grep -E "ANGLE scanout" "$dir/launcher.log" | sed 's/^.*ANGLE scanout/ANGLE scanout/' | grep -v "^ANGLE scanout stats" | sort | uniq -c
  grep -E "ANGLE scanout stats" "$dir/launcher.log" | sed 's/^.*ANGLE scanout/ANGLE scanout/' > "$dir/host-frames.txt"
  echo "host frame windows: $(wc -l < "$dir/host-frames.txt")"; sort -t'(' -k2 -n -r "$dir/host-frames.txt" | head -8
  kill -INT "$launcher" 2>/dev/null; sleep 20; kill -9 "$launcher" 2>/dev/null
  pkill -9 -f uml-darwin-android17 2>/dev/null
  adb disconnect "$SERIAL" >/dev/null 2>&1
  rm -rf "$WORK/instance-$name"
  sleep 5
}

set +e
# The display a 120 Hz phone gives the guest, with no memory limit.
profile full 4G 120 0 720 1280 320
if [ "${PROFILES:-all}" = tier ]; then
  # Busy address spaces move to the JIT after this many instructions.
  for threshold in ${TIERS:-200000000 2000000000}; do
    export UML_JIT_TIER=$threshold
    profile "tier-$threshold" 4G 120 0 720 1280 320 jit
    unset UML_JIT_TIER
  done
  echo "RESULT: interpreter and tiered profiles finished (status $RESULT)."; exit 0
fi
if [ "${PROFILES:-all}" = jit ]; then
  # The same display on the engine that compiles guest code to host code.
  profile jit 4G 120 0 720 1280 320 jit
  echo "RESULT: interpreter and JIT profiles finished (status $RESULT)."; exit 0
fi
if [ "${PROFILES:-all}" = first ]; then
  [ "$RESULT" = 0 ] && { echo "RESULT: first profile completed."; exit 0; }
  echo "RESULT: the first profile failed."; exit 1
fi
# An iPhone 11-class device: 60 Hz, 828x1792, and about 2.1 GiB for the whole
# process (the figure assumed for a 4 GiB phone). First with the guest RAM the
# unchanged rule gives there, then with the smaller guest of the low-memory rule.
profile limited-1408 1408M 60 2098 828 1792 326
profile limited-1024 1024M 60 2098 828 1792 326
set -e
if [ "$RESULT" = 0 ]; then
  echo "RESULT: Android reached boot_completed on the ANGLE path in every profile (macOS host)."
else
  echo "RESULT: at least one profile failed."
  exit 1
fi
