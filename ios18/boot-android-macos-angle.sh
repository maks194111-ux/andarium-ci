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
for tool in autoconf automake libtool pkg-config ninja cmake gptfdisk; do
  HOMEBREW_NO_AUTO_UPDATE=1 brew list "$tool" >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install "$tool"
done
command -v adb >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install --cask android-platform-tools
adb version | head -1; command -v sgdisk

cd "$UPSTREAM"
stage "retarget build system (macOS product, ANGLE host GL)"
python3 "$HERE/engine_build_patch.py" "$UPSTREAM" macos
python3 "$HERE/angle_provider.py" "$UPSTREAM"
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
cmake --preset macos-android17
cmake --build .build/presets/macos-android17 --target uml-darwin-android17 -j 4 -- -k 0
EMULATOR=$(find .build/presets/macos-android17 -name uml-darwin-android17 -type f | head -1)
otool -L "$EMULATOR" | grep -E 'EGL|GLES' || true

stage "boot Android headless on ANGLE"
CPUS=$(sysctl -n hw.ncpu)
set +e
python3 tools/boot_android.py --instance "$WORK/instance" --emulator "$EMULATOR" \
  --display offscreen --cpus "$CPUS" --memory 4G --adb-timeout 1500 --boot-timeout 3000 \
  > "$OUT/launcher.log" 2>&1 &
LAUNCHER=$!
SERIAL=127.0.0.1:5555
booted=0
for i in $(seq 1 330); do
  sleep 10
  kill -0 "$LAUNCHER" 2>/dev/null || { echo "launcher exited"; break; }
  adb connect "$SERIAL" >/dev/null 2>&1
  state=$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  if [ "$state" = 1 ]; then booted=1; echo "boot_completed after about $((i*10)) s"; break; fi
  [ $((i % 12)) -eq 0 ] && { echo "waiting: $((i*10)) s"; tail -2 "$OUT/launcher.log" | cut -c1-200; }
done
if adb -s "$SERIAL" shell true 2>/dev/null; then
  adb -s "$SERIAL" shell 'getprop | grep -E "boot_completed|opengles|hardware.egl|hardware.vulkan|hwui|bootanim|ro.build.version.release"' > "$OUT/props.txt" 2>&1
  adb -s "$SERIAL" shell dumpsys SurfaceFlinger > "$OUT/surfaceflinger.txt" 2>&1
  grep -E "GLES|EGL|Vulkan|refresh|fps" "$OUT/surfaceflinger.txt" | head -30
  adb -s "$SERIAL" logcat -d > "$OUT/logcat.txt" 2>&1
  grep -ciE "FATAL EXCEPTION|Fatal signal" "$OUT/logcat.txt"
  grep -E "FATAL EXCEPTION|Fatal signal|EGL_BAD|eglCreate|GL error|virgl|mesa" "$OUT/logcat.txt" | cut -c1-220 | sort | uniq -c | sort -rn | head -40
  if [ "$booted" = 1 ]; then
    sleep 60
    adb -s "$SERIAL" exec-out screencap -p > "$OUT/screen.png"
    adb -s "$SERIAL" shell input keyevent KEYCODE_HOME
    adb -s "$SERIAL" shell am start -a android.settings.SETTINGS >/dev/null 2>&1
    sleep 30
    for n in 1 2 3 4 5 6; do adb -s "$SERIAL" shell input swipe 360 1000 360 300 300; sleep 1; done
    adb -s "$SERIAL" exec-out screencap -p > "$OUT/settings.png"
    adb -s "$SERIAL" shell dumpsys gfxinfo com.android.settings > "$OUT/gfxinfo-settings.txt" 2>&1
    grep -E "Total frames|Janky frames|percentile|Number" "$OUT/gfxinfo-settings.txt" | head -20
    adb -s "$SERIAL" shell dumpsys SurfaceFlinger --timestats -dump > "$OUT/timestats.txt" 2>&1
  fi
fi
kill -INT "$LAUNCHER" 2>/dev/null; sleep 20; kill -9 "$LAUNCHER" 2>/dev/null
pkill -9 -f uml-darwin-android17 2>/dev/null
set -e
tail -60 "$OUT/launcher.log" | cut -c1-240
grep -iE "renderer=|Virgl|ANGLE|GPU|capset" "$OUT/launcher.log" | sort | uniq -c | sort -rn | head -30 | cut -c1-240
if [ "$booted" = 1 ]; then
  echo "RESULT: Android reached boot_completed on the ANGLE path (macOS host)."
else
  echo "RESULT: Android did not reach boot_completed on the ANGLE path."
  exit 1
fi
