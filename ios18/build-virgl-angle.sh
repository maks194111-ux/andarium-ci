#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Experiment: Andarium's patched virglrenderer on ANGLE's Metal backend (no Metal 4).
# Not a production prefix. Guest Vulkan (Venus) is absent by construction.
set -euo pipefail
UPSTREAM=$(cd "$1" && pwd)
WORK=$(cd "$2" && pwd)
ANGLE=$(cd "$3" && pwd)   # macos/libEGL.dylib, macos/libGLESv2.dylib, include/
HERE=$(cd "$(dirname "$0")" && pwd)
SOURCES="$WORK/sources"
STAGE="$WORK/virgl-angle-prefix"

bash "$UPSTREAM/dependencies/prepare.sh" \
  --product apple-gpu-vulkan-experiment --root "$SOURCES" --cache "$WORK/source-cache"
bash "$UPSTREAM/dependencies/prepare.sh" \
  --product apple-gpu-vulkan-experiment --root "$SOURCES" --verify

export PKG_CONFIG_PATH= PKG_CONFIG_LIBDIR="$STAGE/lib/pkgconfig"
export SDKROOT="$(xcrun --sdk macosx --show-sdk-path)"
export MACOSX_DEPLOYMENT_TARGET=15.0
export CC="$(xcrun --find clang)" CXX="$(xcrun --find clang++)"
export OBJC="$CC" OBJCXX="$CXX"
MESON="python3 -m mesonbuild.mesonmain"
mkdir -p "$STAGE/include/GL" "$STAGE/lib/pkgconfig"

# libepoxy reaches every GL entry point through the one packaged EGL library.
# Point that at ANGLE instead of the Mesa framework.
python3 - "$SOURCES/libepoxy/src/dispatch_common.c" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
old = '#define EGL_LIB "@rpath/MesaEGL.framework/MesaEGL"'
if text.count(old) != 1:
    raise SystemExit("libepoxy provider line not found")
path.write_text(text.replace(old, '#define EGL_LIB "@rpath/libEGL.dylib"'))
PY
$MESON setup "$WORK/epoxy-build" "$SOURCES/libepoxy" --prefix "$STAGE" --libdir lib \
  --buildtype release --wrap-mode=nodownload -Dc_args="-I$ANGLE/include" \
  -Ddefault_library=static -Dtests=false -Dglx=no -Degl=yes -Dx11=false
$MESON compile -C "$WORK/epoxy-build" -j 3
$MESON install -C "$WORK/epoxy-build"

# The renderer's Metal texture lookup compiles against Mesa's interop headers.
# ANGLE offers no such export, so the probe answers "unsupported" and scanouts
# take the readback path, as upstream's software product does.
MESA="$SOURCES/mesa"; [ -d "$MESA" ] || MESA="$SOURCES/Mesa"
install -m 0644 "$MESA/src/gallium/drivers/zink/zink_interop_public.h" "$STAGE/include/GL/"
install -m 0644 "$MESA/include/GL/mesa_glinterop.h" "$STAGE/include/GL/"

$MESON setup "$WORK/virgl-build" "$SOURCES/virglrenderer" --prefix "$STAGE" --libdir lib \
  --buildtype release --wrap-mode=nodownload \
  -Dc_args="-I$ANGLE/include -I$STAGE/include" \
  -Ddefault_library=static -Dtests=false -Dcheck-gl-errors=false -Dvideo=false \
  -Dplatforms=egl -Dvenus=false
$MESON compile -C "$WORK/virgl-build" -j 3
$MESON install -C "$WORK/virgl-build"

"$CC" -std=c11 -Wall -Wextra -Werror -O1 \
  -I "$STAGE/include" -I "$STAGE/include/virgl" -I "$SOURCES/virglrenderer/src" \
  -I "$SOURCES/virglrenderer/src/gallium/include" -I "$ANGLE/include" \
  "$HERE/virgl-angle-probe.c" \
  "$STAGE/lib/libvirglrenderer.a" "$STAGE/lib/libepoxy.a" \
  -Wl,-rpath,"$ANGLE/macos" \
  -framework Metal -framework Foundation -framework IOSurface -framework CoreFoundation \
  -lc++ -o "$WORK/virgl-angle-probe"

python3 - "$WORK/virgl-angle-probe" <<'PY'
import subprocess
import sys
result = subprocess.run([sys.argv[1]], timeout=120)
print("probe exit status", result.returncode, flush=True)
sys.exit(result.returncode != 0)
PY

# --- Andarium's own renderer classes on ANGLE ---------------------------------
ENGINE="$WORK/engine"
rm -rf "$ENGINE"; mkdir -p "$ENGINE"
cp -R "$UPSTREAM/darwin" "$ENGINE/"
python3 "$HERE/angle_provider.py" "$ENGINE"
GPU="$ENGINE/darwin/device/gpu"
# ANGLE's dylibs carry build-relative names; give copies loadable ones.
RUNTIME="$WORK/angle-runtime"; rm -rf "$RUNTIME"; mkdir -p "$RUNTIME"
cp "$ANGLE/macos/libEGL.dylib" "$ANGLE/macos/libGLESv2.dylib" "$RUNTIME/"
install_name_tool -id @rpath/libEGL.dylib "$RUNTIME/libEGL.dylib"
install_name_tool -id @rpath/libGLESv2.dylib "$RUNTIME/libGLESv2.dylib"
otool -L "$RUNTIME/libEGL.dylib"
engine_sources="host_gl_provider.cpp virgl_renderer.cpp device_memory_pool.cpp freed_memory_watch.cpp context_idle_tracker.cpp"
engine_flags=(-std=c++23 -O1 -DUML_GPU_SOFTWARE_RENDERER=1 -DVIRGL_RENDERER_UNSTABLE_APIS
  -I "$GPU" -I "$ENGINE/darwin/platform" -I "$ENGINE/darwin/platform/apple" -I "$ENGINE/darwin/include"
  -I "$ENGINE/darwin/device/vhost_user" -I "$UPSTREAM/kernel/common/gpu"
  -I "$STAGE/include" -I "$STAGE/include/virgl" -I "$SOURCES/virglrenderer/src"
  -I "$SOURCES/virglrenderer/src/gallium/include" -I "$ANGLE/include")

build_engine() { # <out-dir> <extra compiler flags...>
  local out="$1"; shift
  mkdir -p "$out"
  for source in $engine_sources; do
    "$CXX" "$@" "${engine_flags[@]}" -c "$GPU/$source" -o "$out/${source%.cpp}.o"
  done
  "$CXX" "$@" "${engine_flags[@]}" -x objective-c++ -fobjc-arc -c \
    "$ENGINE/darwin/platform/apple/host_gpu_memory.mm" -o "$out/host_gpu_memory.o"
  "$CC" "$@" -O1 -c "$GPU/angle_interop_unsupported.c" -o "$out/angle_interop_unsupported.o"
}

build_engine "$WORK/engine-macos"
"$CXX" "${engine_flags[@]}" -c "$HERE/engine-renderer-angle-test.cpp" -o "$WORK/engine-macos/test.o"
"$CXX" "$WORK"/engine-macos/*.o "$STAGE/lib/libvirglrenderer.a" "$STAGE/lib/libepoxy.a" \
  "$RUNTIME/libEGL.dylib" -Wl,-rpath,"$RUNTIME" \
  -framework Metal -framework Foundation -framework QuartzCore -framework CoreFoundation -framework IOSurface \
  -o "$WORK/engine-renderer-angle-test"
python3 - "$WORK/engine-renderer-angle-test" <<'PY'
import subprocess
import sys
result = subprocess.run([sys.argv[1]], timeout=120)
print("engine test exit status", result.returncode, flush=True)
sys.exit(result.returncode != 0)
PY

# The same engine sources must also compile for the real phone target.
(
  unset MACOSX_DEPLOYMENT_TARGET
  export SDKROOT="$(xcrun --sdk iphoneos --show-sdk-path)"
  build_engine "$WORK/engine-ios" -target arm64-apple-ios18.0 -isysroot "$SDKROOT"
  for object in "$WORK"/engine-ios/*.o; do
    echo "$(basename "$object"): $(xcrun vtool -show-build "$object" | grep -E 'platform|minos' | tr -s ' \n' ' ')"
  done
)
echo "Engine renderer sources compiled for arm64 iOS 18.0 (compile only; not linked into an app)."
