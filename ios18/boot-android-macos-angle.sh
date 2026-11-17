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
stage() { echo; echo "===== STAGE: $* ====="; echo "::notice title=stage::$*"; }
note() { echo "$*"; echo "::notice title=progress::$*"; }

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
if [ "${PROFILES:-all}" = async ]; then
  python3 "$HERE/async_scanout_patch.py" "$UPSTREAM"
fi
python3 "$HERE/qos_patch.py" "$UPSTREAM" engine
python3 "$HERE/tier_patch.py" "$UPSTREAM"
python3 "$HERE/fastclock_patch.py" "$UPSTREAM"
if [ "${PROFILES:-all}" = video ]; then python3 "$HERE/frame_record_patch.py" "$UPSTREAM"; fi
if [ "${PROFILES:-all}" = mapping ]; then
  stage "mapping wait: original correctness tests under both policies"
  bash "$HERE/test_mapping_wait.sh" "$UPSTREAM"
  python3 "$HERE/mapping_wait_patch.py" "$UPSTREAM"
fi
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
  python3 "$HERE/virgl_gles_patch.py" "$SOURCES/virglrenderer"
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
# Savannah answers 502 at times. The sources are pinned by commit, so a mirror
# gives the same content or the checkout fails.
sed -i '' -e 's|https://git.savannah.gnu.org/git/gnulib.git|https://github.com/coreutils/gnulib.git|' \
  -e 's|https://git.savannah.gnu.org/git/libiconv.git|https://github.com/arthenica/libiconv.git|' dependencies/manifest.tsv
bash dependencies/prepare.sh --product macos
bash dependencies/build.sh

stage "accepted Android kernel bundle and release from upstream"
mkdir -p .build/kernel/artifacts .build/android/releases
curl -fsSL --retry 3 -o "$WORK/kernel.tar.gz" \
  https://github.com/imxieyi/Kernarium/releases/download/1.0b9-beta/android-6.18-arm64-4k-20261111-6.18.60-mc2.tar.gz
tar -C .build/kernel/artifacts -xzf "$WORK/kernel.tar.gz"
python3 "$HERE/kernel_window_patch.py" "$UPSTREAM" .build/kernel/artifacts/*
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

if [ "${PROFILES:-all}" = async ]; then
  stage "real GPU synchronization and triple-buffer integrity tests"
  xcrun clang++ -std=c++20 -fobjc-arc -O2 \
    -I"$UPSTREAM/darwin/device/gpu" -I"$PREFIX/include" \
    "$HERE/test_async_scanout.mm" "$UPSTREAM/darwin/device/gpu/angle_scanout.mm" \
    "$PREFIX/lib/libepoxy.a" \
    -F"$(dirname "$EMULATOR")/Frameworks" -framework libEGL \
    -framework Metal -framework Foundation -framework IOSurface \
    -Wl,-rpath,"$(dirname "$EMULATOR")/Frameworks" -o "$WORK/test-async-scanout"
  python3 - "$WORK/test-async-scanout" <<'PYTEST'
import subprocess, sys
result = subprocess.run([sys.argv[1]], timeout=180)
if result.returncode:
    raise SystemExit(f"GPU integrity test failed: {result.returncode}")
PYTEST
fi

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
  if [ "${SAMPLE:-0}" = 1 ]; then export DARWIN_UML_GUEST_SAMPLES="$dir/samples.txt:2000"; fi
  local started=$(date +%s)
  python3 tools/boot_android.py ${GAPPS_RELEASE:+--release "$GAPPS_RELEASE"} --instance "$WORK/instance-$name" --reset --provision --emulator "$EMULATOR" \
    --display offscreen --width "$width" --height "$height" --dpi "$dpi" --audio-output null \
    --cpus "$CPUS" --memory "$memory" --engine "$engine" --adb-timeout 1800 --boot-timeout 3000 \
    > "$dir/launcher.log" 2>&1 &
  local launcher=$!
  local booted=0 i state
  for i in $(seq 1 "${BOOT_TRIES:-300}"); do
    sleep 10
    kill -0 "$launcher" 2>/dev/null || { note "$name: launcher exited"; tail -5 "$dir/launcher.log" | cut -c1-200; break; }
    state=$(guest shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
    if [ "$state" = 1 ]; then booted=1; note "$name: boot_completed after about $(( $(date +%s) - started )) s"; break; fi
  done
  if [ "$booted" = 1 ]; then
    # Let the launcher finish provisioning and the first-boot work settle.
    for i in $(seq 1 30); do
      [ "$(guest shell settings get secure user_setup_complete 2>/dev/null | tr -d '\r')" = 1 ] && break
      sleep 5
    done
    sleep 60
    # How much of the kernel's own mapping allowance (now 1 GiB) is in use.
    note "$name: $(guest shell 'grep -E "MemTotal|VmallocTotal|VmallocUsed" /proc/meminfo; echo threads $(ps -AT | wc -l)' 2>&1 | tr -s ' \r\n' ' ')"
    if [ "${PROFILES:-all}" = mapping ] || [ "${PROFILES:-all}" = aot ]; then
      if [ -n "${EXPECTED_ART_JIT:-}" ]; then
        local art_jit
        art_jit=$(guest shell getprop dalvik.vm.usejit 2>/dev/null | tr -d '\r\n')
        note "$name: ART JIT=$art_jit, expected $EXPECTED_ART_JIT"
        if [ "$art_jit" != "$EXPECTED_ART_JIT" ]; then
          note "RESULT: ART policy is not the expected one; comparison invalid"
          RESULT=1
          kill -INT "$launcher" 2>/dev/null; sleep 10
          pkill -9 -f uml-darwin-android17 2>/dev/null
          return 1
        fi
      fi
      guest shell 'getprop; pm list features; dumpsys SurfaceFlinger' > "$dir/compatibility.txt" 2>&1
      guest shell 'cat /proc/meminfo; cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io; cat /proc/diskstats; dumpsys cpuinfo' > "$dir/resources-before.txt" 2>&1
      ps -ax -o pid=,%cpu=,rss=,comm= | grep '/uml-darwin-android17$' > "$dir/host-resources-before.txt" || true
    fi
    if [ "${SAMPLE:-0}" = 1 ]; then
      # The engine's own sampler, read from the host: which host code (guest
      # kernel, translation, memory paths) and which guest functions the
      # processors run while Settings scrolls.
      local sx=$((width / 2)) slow=$((height * 3 / 4)) shigh=$((height / 4)) lib
      mkdir -p "$dir/elf"
      for lib in /system/lib64/libhwui.so /system/lib64/libgui.so /system/lib64/libui.so /system/lib64/libbinder.so \
          /system/lib64/libutils.so /system/lib64/libandroid_runtime.so /system/lib64/libc++.so /system/lib64/libEGL.so \
          /system/lib64/libminikin.so /system/lib64/libinput.so /system/lib64/libcutils.so /system/lib64/libbase.so \
          /system/lib64/liblog.so /system/lib64/libft2.so /system/lib64/libharfbuzz_ng.so /system/lib64/libsurfaceflinger.so \
          /system/lib64/librenderengine.so /system/lib64/libandroidfw.so /system/lib64/libhidlbase.so /system/lib64/libnativewindow.so \
          /system/bin/surfaceflinger /system/bin/app_process64 /vendor/lib64/venus_gallium_dri.so \
          /apex/com.android.runtime/lib64/bionic/libc.so /apex/com.android.runtime/lib64/bionic/libm.so \
          /apex/com.android.runtime/bin/linker64 /apex/com.android.art/lib64/libart.so /apex/com.android.art/lib64/libartbase.so \
          /apex/com.android.i18n/lib64/libicuuc.so; do
        guest pull "$lib" "$dir/elf/" >/dev/null 2>&1 || echo "could not pull $lib"
      done
      ls "$dir/elf" | wc -l
      guest shell "input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; am start -W -a android.settings.SETTINGS" >/dev/null 2>&1
      sleep 20
      guest shell "for n in 1 2; do input swipe $sx $slow $sx $shigh 1200; input swipe $sx $shigh $sx $slow 1200; done"
      sleep 3; cp "$dir/samples.txt" "$dir/samples-idle-start.txt"
      sleep 20; cp "$dir/samples.txt" "$dir/samples-before.txt"
      # Host-side stacks of the emulator during the scroll: where its guest
      # processor threads wait.
      sample "$(ps -ax -o pid=,comm= | awk '$2 ~ /\/uml-darwin-android17$/ {print $1; exit}')" 20 -file "$dir/host-sample.txt" > /dev/null 2>&1 &
      host_sampler=$!
      guest shell "dumpsys gfxinfo com.android.settings reset >/dev/null"
      guest shell "for n in 1 2 3 4 5 6 7 8 9 10 11 12; do input swipe $sx $slow $sx $shigh 1200; input swipe $sx $shigh $sx $slow 1200; done"
      guest shell "dumpsys gfxinfo com.android.settings framestats" > "$dir/framestats-sample.txt" 2>&1
      sleep 3; cp "$dir/samples.txt" "$dir/samples-after.txt"
      python3 "$HERE/framestats.py" "$name sampled scroll" "$dir/framestats-sample.txt" || true
      wait "$host_sampler"
      echo "--- $name: host stacks during the scroll"
      python3 "$HERE/host_sample_report.py" "$dir/host-sample.txt" 2>&1 | cut -c1-160
      echo "--- $name: idle 20 s, host and guest samples"
      python3 tests/perf/symbolize_guest_samples.py "$dir/samples-before.txt" "$dir/elf" --baseline "$dir/samples-idle-start.txt" --top 25 2>&1 | cut -c1-200
      echo "--- $name: Settings scroll, host and guest samples"
      python3 tests/perf/symbolize_guest_samples.py "$dir/samples-after.txt" "$dir/elf" --baseline "$dir/samples-before.txt" --top 90 2>&1 | cut -c1-200
      echo "--- $name: gadgets during the scroll"
      python3 - "$dir/samples-before.txt" "$dir/samples-after.txt" <<'PYS'
import collections, sys
def read(path):
    kinds = {"guest": 0, "host": 0}; gadgets = collections.Counter()
    for line in open(path, errors="replace"):
        f = line.rstrip("\n").split("\t")
        if f[0] in kinds and len(f) > 2: kinds[f[0]] += int(f[1])
        if f[0] == "gadget" and len(f) > 2: gadgets[f[2]] += int(f[1])
    return kinds, gadgets
(k0, g0), (k1, g1) = read(sys.argv[1]), read(sys.argv[2])
guest, host = k1["guest"] - k0["guest"], k1["host"] - k0["host"]
print(f"samples in translated guest code {guest}, in host code {host}: guest share {100 * guest / max(guest + host, 1):.1f}%")
g1.subtract(g0); total = sum(g1.values()) or 1
for name, count in g1.most_common(40): print(f"  {100 * count / total:6.2f}%  {name}")
PYS
      rm -rf "$dir/elf"
      kill -INT "$launcher" 2>/dev/null; sleep 15; kill -9 "$launcher" 2>/dev/null
      pkill -9 -f uml-darwin-android17 2>/dev/null; adb disconnect "$SERIAL" >/dev/null 2>&1
      rm -rf "$WORK/instance-$name"; sleep 5
      return 0
    fi
    if [ "${CLOCK_COMPARE:-0}" = 1 ] && [ -f "$WORK/probe/micro" ]; then
      guest push "$WORK/probe/micro" /data/local/tmp/micro >/dev/null 2>&1
      guest shell 'chmod 755 /data/local/tmp/micro; /data/local/tmp/micro' 2>&1 | tr -d '\r' | sed "s/^micro/$name:/"
      guest shell 'a=$(cat /proc/uptime); date +%s.%N; cat /proc/uptime' 2>&1 | tr -d '\r' | tr '\n' ' '; echo
    fi
    if [ "${BENCH:-0}" = 1 ]; then
      # Processor-bound work in one process: how fast does each engine run
      # code that is already hot? "user" is processor time, not waiting.
      if [ -f "$WORK/probe/micro" ]; then
        guest push "$WORK/probe/micro" /data/local/tmp/micro >/dev/null 2>&1
        guest shell 'chmod 755 /data/local/tmp/micro; /data/local/tmp/micro' 2>&1 | tr -d '\r' | sed "s/^micro/$name:/"
        for row in "malloc+free 32" "mutex lock" "snprintf of an integer" "libc: clock_gettime"; do
          echo "--- $name: functions under the row '$row'"
          guest shell "cd /data/local/tmp; simpleperf record -e cpu-clock:u -f 4000 -o micro.data ./micro '$row' 2>&1 | tail -2; simpleperf report -i micro.data --sort dso,symbol 2>&1 | grep -E '^(Samples| *[0-9.]+%)' | head -16" 2>&1 | tr -d '\r' | cut -c1-210
        done
        echo "--- $name: where a shell loop of 60000 steps spends processor time"
        guest shell 'cd /data/local/tmp; simpleperf record -e cpu-clock:u -f 2000 -o sh.data sh -c "i=0; while [ \$i -lt 60000 ]; do i=\$((i+1)); done" 2>&1 | tail -2; simpleperf report -i sh.data --sort dso,symbol 2>&1 | grep -E "^(Samples| *[0-9.]+%)" | head -30' 2>&1 | tr -d '\r' | cut -c1-200
        [ "${BENCH_SHORT:-1}" = 1 ] && { kill -INT "$launcher" 2>/dev/null; sleep 15; kill -9 "$launcher" 2>/dev/null; pkill -9 -f uml-darwin-android17 2>/dev/null; adb disconnect "$SERIAL" >/dev/null 2>&1; rm -rf "$WORK/instance-$name"; sleep 5; return 0; }
      fi
      for round in 1 2; do
        echo "--- $name bench round $round: shell loop of 1500000 steps"
        guest shell 'time sh -c "i=0; while [ \$i -lt 1500000 ]; do i=\$((i+1)); done"' 2>&1 | tr -d '\r' | grep -E 'real|user|sys' | tr '\n' ' '; echo
        echo "--- $name bench round $round: gzip of 24 MiB"
        guest shell 'cd /data/local/tmp; time gzip -c blob > /dev/null' 2>&1 | tr -d '\r' | grep -E 'real|user|sys' | tr '\n' ' '; echo
        echo "--- $name bench round $round: sort of 400000 lines"
        guest shell 'cd /data/local/tmp; [ -f lines ] || od -An -tx8 -w8 blob | head -400000 > lines; time sort lines > /dev/null' 2>&1 | tr -d '\r' | grep -E 'real|user|sys' | tr '\n' ' '; echo
        echo "--- $name bench round $round: awk arithmetic, 3000000 steps"
        guest shell 'time awk "BEGIN { s = 0; for (i = 0; i < 3000000; i++) s += i % 7 * 3; print s }"' 2>&1 | tr -d '\r' | grep -E 'real|user|sys|^[0-9]' | tr '\n' ' '; echo
      done
      kill -INT "$launcher" 2>/dev/null; sleep 15; kill -9 "$launcher" 2>/dev/null
      pkill -9 -f uml-darwin-android17 2>/dev/null; adb disconnect "$SERIAL" >/dev/null 2>&1
      rm -rf "$WORK/instance-$name"; sleep 5
      return 0
    fi
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
    if [ "${PROFILES:-all}" = mapping ] || [ "${PROFILES:-all}" = aot ]; then
      guest shell 'cat /proc/meminfo; cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io; cat /proc/diskstats; dumpsys cpuinfo' > "$dir/resources-after.txt" 2>&1
      ps -ax -o pid=,%cpu=,rss=,comm= | grep '/uml-darwin-android17$' > "$dir/host-resources-after.txt" || true
      # Installability and launch are independent of Play listing visibility.
      # No account, contacts, camera access or sign-in is required for this.
      guest install -r "$WORK/telegram.apk" > "$dir/telegram-install.txt" 2>&1
      if grep -q Success "$dir/telegram-install.txt"; then
        local telegram_package
        telegram_package=$(guest shell pm list packages | tr -d '\r' | grep -E '^package:org\.telegram\.messenger(\.web)?$' | sed 's/^package://' | head -1)
        if [ -n "$telegram_package" ]; then
          guest shell "am start -W -n \$(cmd package resolve-activity --brief -c android.intent.category.LAUNCHER $telegram_package | tail -1)" > "$dir/telegram-start.txt" 2>&1
          sleep 15
          guest shell "pidof $telegram_package; dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity'" > "$dir/telegram-alive.txt" 2>&1
          guest exec-out screencap -p > "$dir/telegram.png" 2>/dev/null
          guest shell "am force-stop $telegram_package" >/dev/null 2>&1
        fi
      fi
      guest logcat -d > "$dir/logcat.txt" 2>&1
    fi
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
    # 3b. Which libraries the render thread and the compositor spend their
    #     processor time in, sampled during the same scroll.
    guest root >/dev/null 2>&1; sleep 5
    note "$name: shell is $(guest shell id 2>&1 | tr -d '\r' | cut -c1-40); simpleperf: $(guest shell 'which simpleperf' 2>&1 | tr -d '\r')"
    guest shell "setprop security.perf_harden 0; am start -W -a android.settings.SETTINGS" >/dev/null 2>&1; sleep 4
    sample() {
      local tag=$1 pid=$2 event
      for event in cpu-clock task-clock; do
        guest shell "rm -f /data/local/tmp/perf-$tag.data; simpleperf record -e $event -f 2000 -p $pid --duration 12 -o /data/local/tmp/perf-$tag.data" > "$dir/perf-$tag-record.txt" 2>&1 &
        local recorder=$!
        sleep 1
        guest shell "for n in 1 2 3 4; do input swipe $x $low $x $high 1200; input swipe $x $high $x $low 1200; done"
        wait $recorder
        guest shell "simpleperf report -i /data/local/tmp/perf-$tag.data --sort comm,dso 2>&1" > "$dir/perf-$tag-dso.txt" 2>&1
        guest shell "simpleperf report -i /data/local/tmp/perf-$tag.data --sort comm,dso,symbol 2>&1" > "$dir/perf-$tag-symbol.txt" 2>&1
        grep -q '^Samples: [1-9]' "$dir/perf-$tag-dso.txt" && break
        tail -4 "$dir/perf-$tag-record.txt" | cut -c1-200
      done
      echo "--- $name: processor samples of $tag by thread and library ($event)"
      grep -E '^(Samples|Event count)' "$dir/perf-$tag-dso.txt"
      grep -E '^ *[0-9.]+%' "$dir/perf-$tag-dso.txt" | head -28 | cut -c1-150
      echo "--- $name: $tag by function"
      grep -E '^ *[0-9.]+%' "$dir/perf-$tag-symbol.txt" | head -60 | cut -c1-190
      echo "::notice title=perf $tag::$(grep -E '^ *[0-9.]+%' "$dir/perf-$tag-dso.txt" | head -12 | tr -s ' ' | cut -c1-90 | tr '\n' ';')"
    }
    if [ -f "$WORK/probe/probe.apk" ]; then
      guest install -r "$WORK/probe/probe.apk" 2>&1 | tail -1
      guest shell "am start -W -n local.andarium.probe/.ProbeActivity" >/dev/null 2>&1; sleep 6
      guest shell "input swipe $x $low $x $high 600; input swipe $x $high $x $low 600"; sleep 2
      guest exec-out screencap -p > "$dir/probe.png"
      guest shell "dumpsys gfxinfo local.andarium.probe reset >/dev/null"
      guest shell "for n in 1 2 3 4; do input swipe $x $low $x $high 1200; input swipe $x $high $x $low 1200; done"
      guest shell "dumpsys gfxinfo local.andarium.probe framestats" > "$dir/framestats-probe.txt" 2>&1
      python3 "$HERE/framestats.py" "$name / probe app" "$dir/framestats-probe.txt" || true
      for event in cpu-clock:u task-clock:u cpu-clock; do
        guest shell "simpleperf record --app local.andarium.probe -e $event -f 2000 --duration 12 -o /data/local/tmp/perf-probe.data" > "$dir/perf-probe-record.txt" 2>&1 &
        recorder=$!
        sleep 2
        guest shell "for n in 1 2 3 4; do input swipe $x $low $x $high 1200; input swipe $x $high $x $low 1200; done"
        wait $recorder
        guest shell "simpleperf report -i /data/local/tmp/perf-probe.data --sort comm,dso 2>&1" > "$dir/perf-probe-dso.txt" 2>&1
        guest shell "simpleperf report -i /data/local/tmp/perf-probe.data --sort comm,dso,symbol 2>&1" > "$dir/perf-probe-symbol.txt" 2>&1
        grep -q '^Samples: [1-9]' "$dir/perf-probe-dso.txt" && break
        echo "simpleperf with $event:"; tail -4 "$dir/perf-probe-record.txt" | cut -c1-220
      done
      echo "--- $name: probe application, processor samples by thread and library ($event)"
      grep -E '^(Samples|Event count)' "$dir/perf-probe-dso.txt"
      grep -E '^ *[0-9.]+%' "$dir/perf-probe-dso.txt" | head -40 | cut -c1-160
      echo "--- $name: probe application by function"
      grep -E '^ *[0-9.]+%' "$dir/perf-probe-symbol.txt" | head -90 | cut -c1-200
    else
      echo "no probe application was provided"
    fi
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
      echo "::notice title=frames $name $tag::$(python3 "$HERE/framestats.py" "$name $tag" "$dir/framestats-$tag.txt" 2>/dev/null | grep -E 'issuing|whole frame|UI thread' | tr -s ' ' | tr '\n' ';')"
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
    note "RESULT: profile $name did not reach boot_completed"; RESULT=1
    tail -25 "$dir/launcher.log" | cut -c1-220
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
# The Google image the phone build carries, on a device-like budget: does the
# guest kernel end by itself, and what does it say when it does? The package
# address comes from a repository secret and is never printed.
watch_gapps() {
  local name=$1 memory=$2 limit=$3 cpus=$4 minutes=$5
  local dir="$OUT/$name"; mkdir -p "$dir"
  stage "watch $name: Google image, RAM $memory, limit ${limit} MiB, $cpus vCPUs, $minutes min"
  export UML_GUEST_REFRESH_HZ=60
  if [ "$limit" != 0 ]; then export UML_MEMORY_LIMIT_MIB=$limit; else unset UML_MEMORY_LIMIT_MIB; fi
  local started=$(date +%s) booted=0 i
  python3 tools/boot_android.py --release "$GAPPS_RELEASE" --instance "$WORK/instance-$name" --reset --emulator "$EMULATOR" \
    --display offscreen --width 828 --height 1792 --dpi 326 --audio-output null \
    --cpus "$cpus" --memory "$memory" --engine gadgets --adb-timeout 1800 --boot-timeout 3000 \
    > "$dir/launcher.log" 2>&1 &
  local launcher=$!
  for i in $(seq 1 $((minutes * 3))); do
    sleep 20
    local at=$(( $(date +%s) - started ))
    if ! kill -0 "$launcher" 2>/dev/null; then note "$name: THE EMULATOR ENDED BY ITSELF after $at s (booted=$booted)"; RESULT=1; break; fi
    local line=$(guest shell 'echo "boot=$(getprop sys.boot_completed) anim=$(getprop init.svc.bootanim) $(grep -E "MemAvailable|SwapFree" /proc/meminfo | tr -s " " | tr "\n" " ") $(tr "\n" " " < /proc/pressure/memory | cut -c1-60) procs=$(ls /proc | grep -c "^[0-9]")"' 2>/dev/null | tr -d '\r')
    local runtime_pid=$(ps -ax -o pid=,comm= | awk '$2 ~ /\/uml-darwin-android17$/ {print $1; exit}')
    local runtime_rss=unavailable
    if [ -n "$runtime_pid" ]; then
      runtime_rss=$(ps -o rss= -p "$runtime_pid" 2>/dev/null | awk '{printf "%d MiB", $1/1024}')
    fi
    echo "$name t=${at}s host=$runtime_rss $line"
    case "$line" in boot=1*) if [ "$booted" = 0 ]; then booted=1; note "$name: boot_completed after about $at s"; guest shell "input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard" >/dev/null 2>&1; fi;; esac
    if [ "$booted" = 1 ] && [ $((i % 6)) = 0 ]; then
      guest shell "monkey -p com.android.vending -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1
    fi
  done
  if [ "$booted" != 1 ]; then
    note "$name: Android did not report boot_completed during the watch"
    RESULT=1
  fi
  if ! kill -0 "$launcher" 2>/dev/null; then RESULT=1; fi
  guest exec-out screencap -p > "$dir/screen.png" 2>/dev/null
  guest logcat -d > "$dir/logcat.txt" 2>&1
  guest shell dmesg > "$dir/dmesg.txt" 2>&1
  echo "--- $name: kills and fatal entries in logcat"
  grep -ciE "FATAL EXCEPTION|Fatal signal" "$dir/logcat.txt"
  grep -E "lowmemorykiller|lmkd.*[Kk]ill|Out of memory|oom-kill|FATAL EXCEPTION|Fatal signal|Watchdog|WATCHDOG|init: .*(exited|killed|crash)" "$dir/logcat.txt" | cut -c1-220 | tail -60
  echo "--- $name: launcher log, lines that name a failure"
  grep -n -iE "panic|oops|BUG:|out of memory|oom|killed process|virtual Jetsam|memory limit|short of|host fault|fatal|abort|segfault|unable|cannot|error" "$dir/launcher.log" | cut -c1-240 | tail -80
  echo "--- $name: last 120 lines of the launcher log"
  tail -120 "$dir/launcher.log" | cut -c1-240
  kill -INT "$launcher" 2>/dev/null; sleep 20; kill -9 "$launcher" 2>/dev/null
  pkill -9 -f uml-darwin-android17 2>/dev/null; adb disconnect "$SERIAL" >/dev/null 2>&1
  rm -rf "$WORK/instance-$name"; sleep 5
}
# A real-time recording of the guest's display on the Mac test executable.
# Arguments: name, release directory, what the image is.
# The frames come from the engine's own mirror (frame_record_patch.py), at most
# 60 a second, 720 pixels wide; the guest renders 2048x2732. Setup Wizard is
# closed over adb before the recording, which a person would do by hand.
record_video() {
  local name=$1 release=$2 label=$3
  local dir="$OUT/$name"; mkdir -p "$dir"
  local record="$WORK/$name.frames" events="$dir/events.txt"
  local x=1024 low=2049 high=683
  stage "video $name: $label, RAM 3G, 60 Hz, 2048x2732, $CPUS guest processors"
  export UML_GUEST_REFRESH_HZ=60; unset UML_MEMORY_LIMIT_MIB
  rm -f "$record" "$record.on" "$events"
  mark() { echo "$(python3 -c 'import time; print(time.clock_gettime_ns(time.CLOCK_UPTIME_RAW))') $*" >> "$events"; }
  local started=$(date +%s) booted=0 i
  UML_FRAME_RECORD="$record" python3 tools/boot_android.py --release "$release" --instance "$WORK/instance-$name" --reset --emulator "$EMULATOR" \
    --display offscreen --offscreen-mirror 720@60 --width 2048 --height 2732 --dpi 264 --audio-output null \
    --cpus "$CPUS" --memory 3G --engine gadgets --adb-timeout 1800 --boot-timeout 3000 \
    > "$dir/launcher.log" 2>&1 &
  local launcher=$!
  for i in $(seq 1 120); do
    sleep 10
    kill -0 "$launcher" 2>/dev/null || { note "$name: launcher exited"; tail -5 "$dir/launcher.log" | cut -c1-200; break; }
    if [ "$(guest shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; then
      booted=1; note "$name: boot_completed after about $(( $(date +%s) - started )) s"; break
    fi
  done
  if [ "$booted" != 1 ]; then
    note "RESULT: $name did not reach boot_completed; no video"; RESULT=1
    tail -25 "$dir/launcher.log" | cut -c1-220
  else
    sleep 60
    guest exec-out screencap -p > "$dir/first-boot.png" 2>/dev/null
    guest shell 'settings put global device_provisioned 1; settings put secure user_setup_complete 1
      for wizard in org.lineageos.setupwizard com.google.android.setupwizard; do pm disable-user --user 0 $wizard; am force-stop $wizard; done
      input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard
      am start -W -a android.intent.action.MAIN -c android.intent.category.HOME' > "$dir/provision.txt" 2>&1
    sleep 45
    guest shell 'input keyevent KEYCODE_HOME' >/dev/null 2>&1
    sleep 15
    note "$name: before the recording: ART JIT=$(guest shell getprop dalvik.vm.usejit 2>/dev/null | tr -d '\r\n'), HOME=$(guest shell 'cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME' 2>/dev/null | tr -d '\r' | tail -1), front=$(guest shell 'dumpsys activity activities' 2>/dev/null | tr -d '\r' | grep -m1 -E 'topResumedActivity|mResumedActivity' | tr -s ' ' | cut -c1-120)"
    guest exec-out screencap -p > "$dir/before-recording.png" 2>/dev/null
    guest shell "dumpsys gfxinfo com.android.settings reset >/dev/null 2>&1"
    touch "$record.on"; sleep 2
    mark "home screen, idle"; sleep 4
    mark "Settings opens"
    guest shell "am start -a android.settings.SETTINGS" >/dev/null 2>&1; sleep 8
    mark "Settings list, flings"
    guest shell "for n in 1 2 3 4; do input swipe $x $low $x $high 250; sleep 1; done; for n in 1 2 3 4; do input swipe $x $high $x $low 250; sleep 1; done"
    mark "Settings list, slow drags"
    guest shell "for n in 1 2; do input swipe $x $low $x $high 1200; input swipe $x $high $x $low 1200; done"
    mark "notification shade, three times"
    guest shell "for n in 1 2 3; do cmd statusbar expand-notifications; sleep 2; cmd statusbar collapse; sleep 2; done"
    mark "Google Play opens"
    guest shell "monkey -p com.android.vending -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1; sleep 25
    mark "back to the home screen"
    guest shell "input keyevent KEYCODE_HOME" >/dev/null 2>&1; sleep 6
    mark "application list opens and scrolls"
    guest shell "input swipe $x $low $x $high 300; sleep 4; input swipe $x $low $x $high 600; sleep 2; input swipe $x $high $x $low 600; sleep 2; input keyevent KEYCODE_HOME"; sleep 5
    mark "end"
    sleep 1; rm -f "$record.on"
    guest exec-out screencap -p > "$dir/after-recording.png" 2>/dev/null
    guest shell "dumpsys gfxinfo com.android.settings" > "$dir/gfxinfo-settings.txt" 2>&1
    guest shell "dumpsys gfxinfo com.android.settings framestats" > "$dir/framestats-settings.txt" 2>&1
    python3 "$HERE/framestats.py" "$name / Settings during the recording" "$dir/framestats-settings.txt" || true
    grep -E "Total frames rendered|Janky frames|percentile" "$dir/gfxinfo-settings.txt" | head -8
    guest shell 'pm list packages | grep -E "com.android.vending|com.google.android.gms$"; grep -E "MemTotal|MemAvailable" /proc/meminfo' 2>&1 | tr -d '\r'
    guest logcat -d > "$dir/logcat.txt" 2>&1
    echo "$name: fatal entries in logcat: $(grep -ciE "FATAL EXCEPTION|Fatal signal" "$dir/logcat.txt")"
    grep -E "FATAL EXCEPTION|Fatal signal|ANR in" "$dir/logcat.txt" | cut -c1-200 | head -12
  fi
  kill -0 "$launcher" 2>/dev/null && echo "$name: emulator still running at the end" || { echo "$name: EMULATOR EXITED DURING THE TEST"; RESULT=1; }
  grep -E "Frame record|Offscreen display" "$dir/launcher.log" | cut -c1-200
  kill -INT "$launcher" 2>/dev/null; sleep 20; kill -9 "$launcher" 2>/dev/null
  pkill -9 -f uml-darwin-android17 2>/dev/null; adb disconnect "$SERIAL" >/dev/null 2>&1
  rm -rf "$WORK/instance-$name"; sleep 5
  if [ -s "$record" ]; then
    ls -la "$record"
    PYTHONPATH="$WORK/video-tools${PYTHONPATH:+:$PYTHONPATH}" python3 "$HERE/frames_to_video.py" \
      "$record" "$dir/$name.mp4" "$dir/frame-times.csv" "$events" 2>&1 | tee "$dir/video-summary.txt" || RESULT=1
    [ -s "$dir/$name.mp4" ] || { note "RESULT: $name: the video was not written"; RESULT=1; }
    rm -f "$record"
  elif [ "$booted" = 1 ]; then
    note "RESULT: $name: Android booted but no frame was recorded"; RESULT=1
  fi
  tail -n +1 "$dir/video-summary.txt" 2>/dev/null | head -3 | while read -r line; do echo "::notice title=$name::$line"; done
}
# Where the time goes with the Google image, and whether the answer changes
# once first-boot background work has ended. One boot gives: a timeline of the
# guest's busy share with the busiest processes, the same measured scenario
# right after boot ("fresh") and after the guest went quiet ("settled"),
# repeated cold starts, and a check that an installed app runs and stays alive.
# Arguments: name, release directory, width, height, density, label.
deep_run() {
  local name=$1 release=$2 width=$3 height=$4 dpi=$5 label=$6
  local dir="$OUT/$name"; mkdir -p "$dir"
  local x=$((width / 2)) low=$((height * 3 / 4)) high=$((height / 4))
  stage "deep $name: $label, RAM 3G, 60 Hz, ${width}x${height}, $CPUS guest processors"
  export UML_GUEST_REFRESH_HZ=60; unset UML_MEMORY_LIMIT_MIB
  local started=$(date +%s) booted=0 i
  python3 tools/boot_android.py --release "$release" --instance "$WORK/instance-$name" --reset --emulator "$EMULATOR" \
    --display offscreen --width "$width" --height "$height" --dpi "$dpi" --audio-output null \
    --cpus "$CPUS" --memory 3G --engine gadgets --adb-timeout 1800 --boot-timeout 3000 \
    > "$dir/launcher.log" 2>&1 &
  local launcher=$!
  for i in $(seq 1 120); do
    sleep 10
    kill -0 "$launcher" 2>/dev/null || { note "$name: launcher exited"; tail -5 "$dir/launcher.log" | cut -c1-200; break; }
    if [ "$(guest shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; then
      booted=1; note "$name: boot_completed after about $(( $(date +%s) - started )) s"; break
    fi
  done
  if [ "$booted" != 1 ]; then
    note "RESULT: $name did not reach boot_completed"; RESULT=1
    tail -25 "$dir/launcher.log" | cut -c1-220
  else
    local boot_at=$(date +%s)
    # Busy share of all guest processors over five seconds, then the busiest
    # processes. Prints "busy NN% | name cpu, name cpu, ...".
    busy() {
      local share top
      share=$(guest shell 'head -1 /proc/stat; sleep 5; head -1 /proc/stat' 2>/dev/null | tr -d '\r' | awk '{t=0; for(i=2;i<=9;i++) t+=$i; idle=$5+$6; if (NR==1) {t0=t; i0=idle} else if (t>t0) printf "%.0f", 100*(1-(idle-i0)/(t-t0))}')
      top=$(guest shell 'top -b -n 1 -m 6 -o %CPU,NAME -s 1' 2>/dev/null | tr -d '\r' | awk 'seen && NF>=2 && $1+0 >= 3 {printf "%s %s, ", $2, $1} /%CPU/ {seen=1}')
      echo "busy ${share:-?}% | $top"
    }
    # The measured scenario. Argument: tag.
    scenario() {
      local tag=$1 start_line frames began took
      guest shell "input keyevent KEYCODE_HOME; am force-stop com.android.settings" >/dev/null 2>&1; sleep 2
      start_line=$(guest shell "am start -W -a android.settings.SETTINGS" 2>&1 | tr -d '\r' | grep -E 'LaunchState|TotalTime|WaitTime' | tr '\n' ' ')
      note "$name/$tag: Settings cold start: $start_line"
      sleep 6
      guest exec-out screencap -p > "$dir/$tag-settings.png" 2>/dev/null
      guest shell "input swipe $x $low $x $high 600; input swipe $x $high $x $low 600"; sleep 2
      guest shell "dumpsys gfxinfo com.android.settings reset >/dev/null; dumpsys SurfaceFlinger --timestats -clear -enable" >/dev/null 2>&1
      guest shell "sh /data/local/tmp/threads.sh" > "$dir/$tag-threads-before.txt" 2>&1
      guest shell 'head -1 /proc/stat' > "$dir/$tag-stat-before.txt" 2>&1
      began=$(date +%s)
      guest shell "for n in 1 2 3 4 5 6; do input swipe $x $low $x $high 1200; input swipe $x $high $x $low 1200; done"
      took=$(( $(date +%s) - began ))
      guest shell 'head -1 /proc/stat' > "$dir/$tag-stat-after.txt" 2>&1
      guest shell "sh /data/local/tmp/threads.sh" > "$dir/$tag-threads-after.txt" 2>&1
      guest shell "dumpsys SurfaceFlinger --timestats -dump -maxlayers 6" > "$dir/$tag-timestats-drag.txt" 2>&1
      guest shell "dumpsys gfxinfo com.android.settings" > "$dir/$tag-gfxinfo-drag.txt" 2>&1
      guest shell "dumpsys gfxinfo com.android.settings framestats" > "$dir/$tag-framestats-drag.txt" 2>&1
      frames=$(tr -d '\r' < "$dir/$tag-gfxinfo-drag.txt" | awk '/Total frames rendered/ {print $4}')
      note "$name/$tag: slow drags: ${frames:-0} frames in $took s; $(grep -E 'Janky frames:|50th percentile|90th percentile|99th percentile' "$dir/$tag-gfxinfo-drag.txt" | tr -d '\r' | tr -s ' ' | tr '\n' ';'); guest processors busy $(cat "$dir/$tag-stat-before.txt" "$dir/$tag-stat-after.txt" | tr -d '\r' | awk '{t=0; for(i=2;i<=9;i++) t+=$i; idle=$5+$6; if (NR==1) {t0=t; i0=idle} else if (t>t0) printf "%.0f%%", 100*(1-(idle-i0)/(t-t0))}')"
      python3 "$HERE/framestats.py" "$name/$tag drags" "$dir/$tag-framestats-drag.txt" || true
      python3 "$HERE/split.py" "$name/$tag drags" "$dir/$tag-threads-before.txt" "$dir/$tag-threads-after.txt" "${frames:-0}" "$took" || true
      grep -E "^(totalFrames|missedFrames|clientCompositionFrames)|averageFPS" "$dir/$tag-timestats-drag.txt" | tr -d '\r' | head -8 | cut -c1-140
      guest shell "dumpsys gfxinfo com.android.settings reset >/dev/null" >/dev/null 2>&1
      guest shell "for n in 1 2 3 4; do input swipe $x $low $x $high 250; sleep 1; done; for n in 1 2 3 4; do input swipe $x $high $x $low 250; sleep 1; done"
      guest shell "dumpsys gfxinfo com.android.settings" > "$dir/$tag-gfxinfo-fling.txt" 2>&1
      note "$name/$tag: flings: $(grep -E 'Total frames rendered|Janky frames:|50th percentile|90th percentile|99th percentile' "$dir/$tag-gfxinfo-fling.txt" | tr -d '\r' | tr -s ' ' | tr '\n' ';')"
      guest shell "dumpsys gfxinfo com.android.systemui reset >/dev/null" >/dev/null 2>&1
      guest shell "for n in 1 2 3; do cmd statusbar expand-notifications; sleep 2; cmd statusbar collapse; sleep 2; done"
      guest shell "dumpsys gfxinfo com.android.systemui" > "$dir/$tag-gfxinfo-shade.txt" 2>&1
      guest shell "dumpsys gfxinfo com.android.systemui framestats" > "$dir/$tag-framestats-shade.txt" 2>&1
      note "$name/$tag: shade: $(grep -E 'Total frames rendered|Janky frames:|50th percentile|90th percentile|99th percentile' "$dir/$tag-gfxinfo-shade.txt" | tr -d '\r' | tr -s ' ' | tr '\n' ';')"
      python3 "$HERE/framestats.py" "$name/$tag shade" "$dir/$tag-framestats-shade.txt" || true
      guest shell "cmd statusbar expand-notifications" >/dev/null 2>&1; sleep 3
      guest exec-out screencap -p > "$dir/$tag-shade.png" 2>/dev/null
      guest shell "cmd statusbar collapse; input keyevent KEYCODE_HOME; am force-stop com.android.vending" >/dev/null 2>&1; sleep 2
      began=$(python3 -c 'import time; print(time.time())')
      start_line=$(guest shell "am start -W -n com.android.vending/.AssetBrowserActivity" 2>&1 | tr -d '\r' | grep -E 'LaunchState|TotalTime|WaitTime|Error' | tr '\n' ' ')
      note "$name/$tag: Google Play cold start: $start_line(host wall $(python3 -c "import time; print(round(time.time() - $began, 1))") s)"
      sleep 12
      guest exec-out screencap -p > "$dir/$tag-play.png" 2>/dev/null
      guest shell "input keyevent KEYCODE_HOME" >/dev/null 2>&1; sleep 3
    }
    sleep 60
    guest shell 'settings put global device_provisioned 1; settings put secure user_setup_complete 1
      for wizard in org.lineageos.setupwizard com.google.android.setupwizard; do pm disable-user --user 0 $wizard; am force-stop $wizard; done
      input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard
      am start -W -a android.intent.action.MAIN -c android.intent.category.HOME' > "$dir/provision.txt" 2>&1
    sleep 45
    guest shell 'input keyevent KEYCODE_HOME' >/dev/null 2>&1; sleep 10
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
    guest exec-out screencap -p > "$dir/home.png" 2>/dev/null
    note "$name: ART JIT=$(guest shell getprop dalvik.vm.usejit 2>/dev/null | tr -d '\r\n'); $(( $(date +%s) - boot_at )) s after boot: $(busy)"
    # Processor placement. A phone keeps background work on a few cores; this
    # guest's groups all span every core. DEEP_TUNE=1 confines background
    # groups and background compilation, as a device's init script would.
    guest root >/dev/null 2>&1; sleep 6
    if [ "${DEEP_TUNE:-0}" = 1 ]; then
      guest shell 'echo 0 > /dev/cpuset/background/cpus; echo 0-1 > /dev/cpuset/system-background/cpus; echo 0-1 > /dev/cpuset/restricted/cpus
        setprop dalvik.vm.background-dex2oat-cpu-set 0; setprop dalvik.vm.background-dex2oat-threads 1
        setprop dalvik.vm.dex2oat-cpu-set 0,1; setprop dalvik.vm.dex2oat-threads 2' > "$dir/tune.txt" 2>&1
    fi
    placement() {
      guest shell 'id | cut -c1-30; for g in background system-background restricted foreground top-app; do echo "$g: $(cat /dev/cpuset/$g/cpus 2>&1)"; done
        for p in $(pgrep -f "vending|gms|dex2oat|system_server|surfaceflinger|settings"); do echo "$(cat /proc/$p/cmdline | tr "\0" " " | cut -c1-48) | $(cat /proc/$p/cpuset) | $(grep Cpus_allowed_list /proc/$p/status | tr -s "\t " " ")"; done' 2>&1 | tr -d '\r'
    }
    placement > "$dir/placement-fresh.txt"
    note "$name: tune=${DEEP_TUNE:-0}; $(head -6 "$dir/placement-fresh.txt" | tr '\n' ';' | cut -c1-200)"
    guest shell 'top -b -n 1 -m 20 -o %CPU,RES,NAME -s 1' > "$dir/fresh-top.txt" 2>&1
    guest shell 'cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io; cat /proc/loadavg; grep -E "MemTotal|MemAvailable|SwapTotal|SwapFree" /proc/meminfo; cat /proc/diskstats' > "$dir/fresh-resources.txt" 2>&1
    scenario fresh
    # Wait for the guest to go quiet: two samples in a row under 15% busy, at
    # most SETTLE_MINUTES. The timeline is the finding, not just the end.
    local quiet=0 line
    for i in $(seq 1 $(( ${SETTLE_MINUTES:-8} * 2 ))); do
      line=$(busy)
      echo "$name settle t=$(( $(date +%s) - boot_at ))s $line"
      case "$line" in "busy ?%"*) ;; *) if [ "$(echo "$line" | sed -E 's/^busy ([0-9]+)%.*/\1/')" -lt 15 ]; then quiet=$((quiet + 1)); else quiet=0; fi;; esac
      [ "$quiet" -ge 2 ] && break
      sleep 24
    done
    note "$name: guest quiet=$quiet (2 means settled) $(( $(date +%s) - boot_at )) s after boot: $(busy)"
    placement > "$dir/placement-settled.txt"; grep -E "vending|dex2oat|gms" "$dir/placement-settled.txt" | head -8
    guest shell 'top -b -n 1 -m 20 -o %CPU,RES,NAME -s 1' > "$dir/settled-top.txt" 2>&1
    guest shell 'cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io; cat /proc/loadavg; grep -E "MemTotal|MemAvailable|SwapTotal|SwapFree" /proc/meminfo; cat /proc/diskstats' > "$dir/settled-resources.txt" 2>&1
    scenario settled
    scenario settled2
    if [ "${DEEP_ASYNC:-0}" = 1 ]; then
      if [ "$quiet" -lt 2 ]; then
        echo "RESULT: guest did not settle; no performance claim may be made"
      fi
      # Same engine/image/session; only the producer's synchronization changes.
      # Alternate order to reduce drift. Flush the setting before every run.
      local variant round
      for round in 1 2 3; do
        local order="0 1"
        [ "$round" = 2 ] && order="1 0"
        for variant in $order; do
          printf '%s\n' "$variant" > "$UML_ANGLE_ASYNC_CONTROL"
          sleep 5
          scenario "async${round}-${variant}"
        done
      done
    fi
    if [ "${DEEP_AB:-0}" = 1 ]; then
      # One boot, one background state, alternating variants: the shipped
      # setting, window blur off, and the interface drawn at half size and
      # scaled by the compositor (the display itself stays ${width}x${height}).
      local round fx=$x flow=$low fhigh=$high
      guest shell 'getprop' > "$dir/getprop.txt" 2>&1
      for round in 1 2 3; do
        scenario "ab$round-base"
        guest shell 'settings put global disable_window_blurs 1' >/dev/null 2>&1; sleep 3
        scenario "ab$round-noblur"
        guest shell 'settings put global disable_window_blurs 0' >/dev/null 2>&1
        guest shell "wm size $((width / 2))x$((height / 2)); wm density $((dpi / 2))" >/dev/null 2>&1; sleep 8
        x=$((fx / 2)); low=$((flow / 2)); high=$((fhigh / 2))
        scenario "ab$round-half"
        x=$fx; low=$flow; high=$fhigh
        guest shell "wm size reset; wm density reset" >/dev/null 2>&1; sleep 8
      done
    fi
    if [ "${DEEP_APP:-0}" = 1 ] && [ -s "$WORK/telegram.apk" ]; then
      local began=$(date +%s) package
      guest install -r "$WORK/telegram.apk" > "$dir/telegram-install.txt" 2>&1
      note "$name: Telegram install: $(tail -1 "$dir/telegram-install.txt" | tr -d '\r' | cut -c1-80) in $(( $(date +%s) - began )) s"
      package=$(guest shell pm list packages | tr -d '\r' | grep -E '^package:org\.telegram\.messenger(\.web)?$' | sed 's/^package://' | head -1)
      if [ -n "$package" ]; then
        note "$name: Telegram first start: $(guest shell "am start -W -n \$(cmd package resolve-activity --brief -c android.intent.category.LAUNCHER $package | tail -1)" 2>&1 | tr -d '\r' | grep -E 'LaunchState|TotalTime|WaitTime|Error' | tr '\n' ' ')"
        sleep 15
        guest exec-out screencap -p > "$dir/telegram.png" 2>/dev/null
        guest shell "input keyevent KEYCODE_HOME" >/dev/null 2>&1; sleep 2
        guest shell "am start -W -a android.settings.SETTINGS" >/dev/null 2>&1; sleep 5
        guest shell "input keyevent KEYCODE_APP_SWITCH" >/dev/null 2>&1; sleep 5
        guest exec-out screencap -p > "$dir/recents.png" 2>/dev/null
        guest shell "input keyevent KEYCODE_HOME" >/dev/null 2>&1; sleep 60
        note "$name: Telegram after 60 s in the background: process $(guest shell "pidof $package" 2>/dev/null | tr -d '\r\n' | sed 's/^$/GONE/'); return: $(guest shell "am start -W -n \$(cmd package resolve-activity --brief -c android.intent.category.LAUNCHER $package | tail -1)" 2>&1 | tr -d '\r' | grep -E 'LaunchState|TotalTime|Error' | tr '\n' ' ')"
        sleep 4
        guest exec-out screencap -p > "$dir/telegram-return.png" 2>/dev/null
        guest shell "input keyevent KEYCODE_HOME" >/dev/null 2>&1
      fi
    fi
    guest shell 'dumpsys cpuinfo' > "$dir/cpuinfo.txt" 2>&1
    guest logcat -d > "$dir/logcat.txt" 2>&1
    echo "$name: fatal entries in logcat: $(grep -ciE "FATAL EXCEPTION|Fatal signal" "$dir/logcat.txt")"
    grep -E "FATAL EXCEPTION|Fatal signal|ANR in" "$dir/logcat.txt" | cut -c1-200 | sort -k6 | uniq -c -f5 | head -12
    echo "--- $name: activities displayed"
    grep -E "ActivityTaskManager: Displayed" "$dir/logcat.txt" | sed -E 's/^[0-9-]+ ([0-9:.]+).*Displayed ([^ ]+) for user 0: (.*)$/\1 \2 \3/' | cut -c1-150
    echo "--- $name: dex2oat and package work seen in the log"
    grep -ciE "dex2oat|BackgroundDexOpt|PackageManagerDexOptimizer" "$dir/logcat.txt"
    grep -E "dex2oat.*(took|Explicit)|BackgroundDexOpt" "$dir/logcat.txt" | cut -c1-180 | head -12
  fi
  kill -0 "$launcher" 2>/dev/null && echo "$name: emulator still running at the end" || { echo "$name: EMULATOR EXITED DURING THE TEST"; RESULT=1; }
  kill -INT "$launcher" 2>/dev/null; sleep 20; kill -9 "$launcher" 2>/dev/null
  pkill -9 -f uml-darwin-android17 2>/dev/null; adb disconnect "$SERIAL" >/dev/null 2>&1
  rm -rf "$WORK/instance-$name"; sleep 5
}
DEEP=0; case "${PROFILES:-all}" in deepres|deepaot|deepcpu|deepab|deepapp|async) DEEP=1;; esac
if [ "${PROFILES:-all}" = gapps ] || [ "${PROFILES:-all}" = mapping ] || [ "${PROFILES:-all}" = aot ] || [ "${PROFILES:-all}" = video ] || [ "$DEEP" = 1 ]; then
  source_url="${GAPPS_IPA_URL:-}"
  if [ "${PROFILES:-all}" = aot ] || [ "${PROFILES:-all}" = video ] || [ "$DEEP" = 1 ]; then source_url="${GAPPS_FIX9_IPA_URL:-}"; fi
  if [ "${PROFILES:-all}" = video ]; then
    stage "tools for the video (ffmpeg, LZ4 reader)"
    command -v ffmpeg >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install ffmpeg >/dev/null 2>&1
    ffmpeg -version | head -1 || { echo "RESULT: ffmpeg could not be installed."; exit 1; }
    python3 -m pip install --quiet --target "$WORK/video-tools" lz4==4.4.4 || { echo "RESULT: the LZ4 reader could not be installed."; exit 1; }
  fi
  [ -n "$source_url" ] || { echo "RESULT: no package address was provided."; exit 1; }
  stage "the Google image of the phone build"
  curl -fsSL --retry 3 -o "$WORK/gapps.ipa" "$source_url" 2>/dev/null || { echo "RESULT: the package could not be fetched."; exit 1; }
  STOCK=$(ls -d "$UPSTREAM"/.build/android/releases/*/ | head -1)
  GAPPS_RELEASE="$UPSTREAM/.build/android/releases/andarium-gapps-experimental-20261114-profiled"
  cp -R "$STOCK" "$GAPPS_RELEASE"
  for entry in release-manifest.json boot/kernel-command-line.txt guest/partition-layout.json guest/system.img; do
    unzip -p "$WORK/gapps.ipa" "Payload/Andarium.app/andarium-system/$entry" > "$GAPPS_RELEASE/$entry"
  done
  rm -f "$WORK/gapps.ipa"; ls -la "$GAPPS_RELEASE/guest"; export GAPPS_RELEASE
  shasum -a 256 "$GAPPS_RELEASE/guest/system.img" > "$OUT/baseline-system-sha256.txt"
  if [ "${PROFILES:-all}" = async ]; then
    export UML_ANGLE_ASYNC_CONTROL="$WORK/async-control"
    printf '0\n' > "$UML_ANGLE_ASYNC_CONTROL"
    curl -fsSL --retry 2 -o "$WORK/telegram.apk" https://telegram.org/dl/android/apk || true
    SETTLE_MINUTES=25 DEEP_ASYNC=1 DEEP_APP=1 deep_run async "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image, synchronous versus GPU-event scanout"
    echo "RESULT: GPU-event scanout comparison finished (status $RESULT)."
    exit "$RESULT"
  fi
  if [ "${PROFILES:-all}" = deepres ]; then
    # Same image and engine, three guest resolutions, FIX9's own resolution at
    # both ends to show the host's drift. Density scales with the width, so
    # the interface keeps its physical size.
    curl -fL --retry 3 -o "$WORK/telegram.apk" https://telegram.org/dl/android/apk || true
    DEEP_APP=1 deep_run res-2048-first "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image, full resolution"
    deep_run res-1280 "$GAPPS_RELEASE" 1280 1707 165 "FIX9 image, 1280x1707"
    deep_run res-1024 "$GAPPS_RELEASE" 1024 1366 132 "FIX9 image, 1024x1366"
    deep_run res-2048-last "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image, full resolution"
    echo "RESULT: resolution comparison finished (status $RESULT)."
    exit "$RESULT"
  fi
  if [ "${PROFILES:-all}" = deepcpu ]; then
    # Same image, engine and resolution; background work confined or not.
    deep_run cpu-fix9-first "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image, background on every core"
    DEEP_TUNE=1 deep_run cpu-confined-1 "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image, background confined"
    DEEP_TUNE=1 deep_run cpu-confined-2 "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image, background confined"
    deep_run cpu-fix9-last "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image, background on every core"
    echo "RESULT: background placement comparison finished (status $RESULT)."
    exit "$RESULT"
  fi
  if [ "${PROFILES:-all}" = deepapp ]; then
    # An installed application: first start, the recent-apps screen, a minute
    # in the background, return.
    curl -fL --retry 3 -o "$WORK/telegram.apk" https://telegram.org/dl/android/apk || true
    SETTLE_MINUTES=2 DEEP_APP=1 deep_run app "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image, installed application"
    echo "RESULT: installed application check finished (status $RESULT)."
    exit "$RESULT"
  fi
  if [ "${PROFILES:-all}" = deepab ]; then
    curl -fL --retry 3 -o "$WORK/telegram.apk" https://telegram.org/dl/android/apk || true
    SETTLE_MINUTES=25 DEEP_AB=1 DEEP_APP=1 deep_run ab "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image, alternating variants in one boot"
    echo "RESULT: alternating comparison finished (status $RESULT)."
    exit "$RESULT"
  fi
  if [ "${PROFILES:-all}" = deepaot ]; then
    [ -n "${GAPPS_AOT_RELEASE_URL:-}" ] || { echo "RESULT: no private AOT release address"; exit 1; }
    AOT_RELEASE="$UPSTREAM/.build/android/releases/andarium-gapps-full-aot-experiment"
    cp -R "$STOCK" "$AOT_RELEASE"
    curl -fsSL --retry 3 -o "$WORK/aot-release.zip" "$GAPPS_AOT_RELEASE_URL" 2>/dev/null || { echo "RESULT: private AOT release fetch failed"; exit 1; }
    for entry in release-manifest.json boot/kernel-command-line.txt guest/partition-layout.json guest/system.img; do
      unzip -p "$WORK/aot-release.zip" "$entry" > "$AOT_RELEASE/$entry"
    done
    rm -f "$WORK/aot-release.zip"
    deep_run aot-fix9-first "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image (ART JIT on)"
    deep_run aot-aot-1 "$AOT_RELEASE" 2048 2732 264 "ahead-of-time image (ART JIT off)"
    deep_run aot-aot-2 "$AOT_RELEASE" 2048 2732 264 "ahead-of-time image (ART JIT off)"
    deep_run aot-fix9-last "$GAPPS_RELEASE" 2048 2732 264 "FIX9 image (ART JIT on)"
    echo "RESULT: FIX9 against ahead-of-time image finished (status $RESULT)."
    exit "$RESULT"
  fi
  if [ "${PROFILES:-all}" = video ]; then
    record_video video-fix9 "$GAPPS_RELEASE" "Google image of the FIX9 build"
    if [ "${VIDEO_AOT:-1}" = 1 ] && [ -n "${GAPPS_AOT_RELEASE_URL:-}" ]; then
      AOT_RELEASE="$UPSTREAM/.build/android/releases/andarium-gapps-full-aot-experiment"
      cp -R "$STOCK" "$AOT_RELEASE"
      if curl -fsSL --retry 3 -o "$WORK/aot-release.zip" "$GAPPS_AOT_RELEASE_URL" 2>/dev/null; then
        for entry in release-manifest.json boot/kernel-command-line.txt guest/partition-layout.json guest/system.img; do
          unzip -p "$WORK/aot-release.zip" "$entry" > "$AOT_RELEASE/$entry"
        done
        rm -f "$WORK/aot-release.zip"
        record_video video-aot "$AOT_RELEASE" "experimental image compiled ahead of time, ART JIT off"
      else
        note "video-aot: the experimental image could not be fetched; only FIX9 was recorded"
      fi
    fi
    echo "RESULT: video recording finished (status $RESULT)."
    exit "$RESULT"
  fi
  if [ "${PROFILES:-all}" = aot ]; then
    [ -n "${GAPPS_AOT_RELEASE_URL:-}" ] || { echo "RESULT: no private AOT release address"; exit 1; }
    actual=$(awk '{print $1}' "$OUT/baseline-system-sha256.txt")
    [ -n "${EXPECTED_BASELINE_SYSTEM_SHA256:-}" ] && [ "$actual" = "$EXPECTED_BASELINE_SYSTEM_SHA256" ] || {
      echo "RESULT: the source image is not FIX9; refusing a mislabeled comparison."
      exit 1
    }
    AOT_RELEASE="$UPSTREAM/.build/android/releases/andarium-gapps-full-aot-experiment"
    cp -R "$STOCK" "$AOT_RELEASE"
    curl -fsSL --retry 3 -o "$WORK/aot-release.zip" "$GAPPS_AOT_RELEASE_URL" 2>/dev/null || {
      echo "RESULT: private AOT release fetch failed"; exit 1;
    }
    for entry in release-manifest.json boot/kernel-command-line.txt guest/partition-layout.json guest/system.img; do
      unzip -p "$WORK/aot-release.zip" "$entry" > "$AOT_RELEASE/$entry"
    done
    rm -f "$WORK/aot-release.zip"
    curl -fL --retry 3 -o "$WORK/telegram.apk" https://telegram.org/dl/android/apk
    shasum -a 256 "$WORK/telegram.apk" > "$OUT/telegram-download-sha256.txt"
    CPUS=4
    BASELINE_RELEASE="$GAPPS_RELEASE"
    # Same CPU count and screen geometry isolate the image/ART policy.
    # This is a lab comparison, not a four-core cap for the iPad app.
    EXPECTED_ART_JIT=true profile aot-A1 3G 60 0 2048 2732 264 gadgets
    GAPPS_RELEASE="$AOT_RELEASE"
    EXPECTED_ART_JIT=false profile aot-B1 3G 60 0 2048 2732 264 gadgets
    EXPECTED_ART_JIT=false profile aot-B2 3G 60 0 2048 2732 264 gadgets
    GAPPS_RELEASE="$BASELINE_RELEASE"
    EXPECTED_ART_JIT=true profile aot-A2 3G 60 0 2048 2732 264 gadgets
    echo "RESULT: full-AOT/no-ART-JIT ABBA comparison finished (status $RESULT)."
    exit "$RESULT"
  fi
  if [ "${PROFILES:-all}" = mapping ]; then
    # Same binary, image, geometry and CPU count, alternating order to reduce
    # host drift. The original algorithm is FIX9's. No sampling during timing.
    CPUS=4
    curl -fL --retry 3 -o "$WORK/telegram.apk" https://telegram.org/dl/android/apk
    shasum -a 256 "$WORK/telegram.apk" > "$OUT/telegram-download-sha256.txt"
    UML_MAPPING_WAIT=0 profile mapping-A1 3G 60 0 828 1792 326 gadgets
    UML_MAPPING_WAIT=1 profile mapping-B1 3G 60 0 828 1792 326 gadgets
    UML_MAPPING_WAIT=1 profile mapping-B2 3G 60 0 828 1792 326 gadgets
    UML_MAPPING_WAIT=0 profile mapping-A2 3G 60 0 828 1792 326 gadgets
    echo "RESULT: Google image mapping-wait ABBA comparison finished (status $RESULT)."
    exit "$RESULT"
  fi
  watch_gapps gapps-1408 1408M 2098 6 ${WATCH_MINUTES:-28}
  echo "RESULT: Google image watch finished (status $RESULT)."; exit "$RESULT"
fi
if [ "${PROFILES:-all}" = text ]; then
  # Missing text: which part of the GPU text path fails, with the renderer's
  # GLES-host log and the guest's own GL checks.
  dir="$OUT/text"; mkdir -p "$dir"
  set +e
  export VREND_DEBUG=${TEXT_VREND_DEBUG:-gles,bgra,feat,tweak,glsl} VIRGL_LOG_LEVEL=debug VIRGL_LOG_FILE="$dir/virgl.log"
  if [ "${TEXT_USE_INTEGER:-1}" = 1 ]; then export VIRGL_USE_INTEGER=1; fi
  export UML_GUEST_REFRESH_HZ=60
  python3 tools/boot_android.py --instance "$WORK/instance-text" --reset --provision --emulator "$EMULATOR" \
    --display offscreen --width 720 --height 1280 --dpi 320 --audio-output null \
    --cpus "$CPUS" --memory 4G --engine gadgets --adb-timeout 1800 --boot-timeout 3000 \
    > "$dir/launcher.log" 2>&1 &
  launcher=$!
  booted=0
  for i in $(seq 1 300); do
    sleep 10
    kill -0 "$launcher" 2>/dev/null || { note "text: launcher exited"; break; }
    [ "$(guest shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] && { booted=1; break; }
  done
  note "text: booted=$booted"
  if [ "$booted" = 1 ]; then
    sleep 60
    guest shell "input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard" >/dev/null 2>&1
    guest push "$WORK/probe/gltext" /data/local/tmp/gltext >/dev/null 2>&1
    guest shell 'chmod 755 /data/local/tmp/gltext; /data/local/tmp/gltext' > "$dir/gltext.txt" 2>&1
    cat "$dir/gltext.txt"
    guest install -r "$WORK/probe/probe.apk" 2>&1 | tail -1
    guest shell "am start -W -n local.andarium.probe/.TextProbeActivity" >/dev/null 2>&1; sleep 10
    guest exec-out screencap -p > "$dir/text-probe.png"
    guest shell "am start -W -a android.settings.SETTINGS" >/dev/null 2>&1; sleep 15
    guest exec-out screencap -p > "$dir/settings.png"
    guest shell "dumpsys gfxinfo local.andarium.probe" > "$dir/gfxinfo-probe.txt" 2>&1
    guest shell "getprop" > "$dir/getprop.txt" 2>&1
    guest logcat -d > "$dir/logcat.txt" 2>&1
  fi
  kill -INT "$launcher" 2>/dev/null; sleep 15; kill -9 "$launcher" 2>/dev/null
  pkill -9 -f uml-darwin-android17 2>/dev/null
  ls -la "$dir"; grep -a -iE "error|fail|unsupported|emulat" "$dir/virgl.log" | sed 's/[0-9]\+/N/g' | sort | uniq -c | sort -rn | head -60
  echo "RESULT: text check finished (booted=$booted)."; exit 0
fi
if [ "${PROFILES:-all}" = sample ]; then
  export SAMPLE=1
  profile sample 4G 120 0 720 1280 320 gadgets
  echo "RESULT: sampled scroll finished."; exit 0
fi
if [ "${PROFILES:-all}" = cpus8 ]; then
  # A device report: an iPad with 8 guest processors and 3 GiB stopped ten
  # seconds into its start. The same engine with those two numbers.
  CPUS=8
  profile cpus8 3G 60 0 720 1280 320 gadgets
  echo "RESULT: eight-processor start finished (status $RESULT)."; exit 0
fi
if [ "${PROFILES:-all}" = clock ]; then
  # The same build twice in one job: time queries through the guest kernel,
  # then answered by the engine.
  export CLOCK_COMPARE=1
  UML_FAST_CLOCK=0 profile clock-kernel 4G 60 0 720 1280 320 gadgets
  profile clock-fast 4G 60 0 720 1280 320 gadgets
  echo "RESULT: clock comparison finished (status $RESULT)."; exit 0
fi
if [ "${PROFILES:-all}" = bench ]; then
  export BENCH=1
  profile bench-interpreter 4G 60 0 720 1280 320 gadgets
  echo "RESULT: engine benchmark finished."; exit 0
fi
# The display a 120 Hz phone gives the guest, with no memory limit.
profile full 4G 120 0 720 1280 320
if [ "${PROFILES:-all}" = tier ]; then
  # Busy address spaces move to the JIT after this many instructions.
  for threshold in ${TIERS:-200000000 2000000000}; do
    export UML_JIT_TIER=$threshold BOOT_TRIES=90
    profile "tier-$threshold" 4G 120 0 720 1280 320 jit
    unset UML_JIT_TIER BOOT_TRIES
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
