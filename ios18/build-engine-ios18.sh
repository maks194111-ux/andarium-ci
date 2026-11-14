#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Staged attempt at the Andarium device runtime for iOS 18 on the ANGLE path.
# Each stage prints a banner; the first failing stage ends the run.
set -euo pipefail
UPSTREAM=$(cd "$1" && pwd)
WORK=$(cd "$2" && pwd)
ANGLE=$(cd "$3" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
stage() { echo; echo "===== STAGE: $* ====="; }

# Upstream's scripts look for a meson executable; the pinned one is a module.
mkdir -p "$WORK/tools"
printf '#!/bin/sh\nexec python3 -m mesonbuild.mesonmain "$@"\n' > "$WORK/tools/meson"
chmod +x "$WORK/tools/meson"
export PATH="$WORK/tools:$PATH"
# Build-only host tools upstream's dependency scripts expect.
for tool in autoconf automake libtool pkg-config ninja cmake; do
  command -v "${tool/libtool/glibtoolize}" >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install "$tool"
done

cd "$UPSTREAM"
stage "retarget build system"
python3 "$HERE/engine_build_patch.py" "$UPSTREAM"
python3 "$HERE/angle_provider.py" "$UPSTREAM"
python3 "$HERE/engine_api_patch.py" "$UPSTREAM"
python3 "$HERE/refresh_patch.py" "$UPSTREAM" engine
python3 "$HERE/angle_scanout.py" "$UPSTREAM"

stage "GPU prefix: libepoxy and virglrenderer for arm64 iOS 18 on ANGLE"
bash dependencies/prepare.sh --product apple-gpu-vulkan-experiment
SOURCES="$UPSTREAM/external/sources"
PREFIX="$UPSTREAM/.build/dependencies/apple-gpu-vulkan-experiment/ios-device-arm64"
BUILD="$WORK/gpu-ios-build"
rm -rf "$PREFIX" "$BUILD"; mkdir -p "$PREFIX/include/GL" "$PREFIX/lib/pkgconfig" "$PREFIX/Frameworks" "$BUILD"
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
CC=$(xcrun --find clang); CXX=$(xcrun --find clang++)
python3 - "$BUILD" "$CC" "$CXX" "$SDK" "$PREFIX" "$ANGLE" <<'PY'
import sys
build, cc, cxx, sdk, prefix, angle = sys.argv[1:]
flags = ['-arch', 'arm64', '-target', 'arm64-apple-ios18.0', '-isysroot', sdk,
         f'-I{prefix}/include', f'-I{angle}/include']
link = flags[:6] + [f'-L{prefix}/lib', '-lobjc']
for name, system in (('epoxy', "system = 'ios'"),
                     ('virgl', "system = 'darwin'\nkernel = 'xnu'\nsubsystem = 'ios'")):
    with open(f'{build}/{name}.cross', 'w') as out:
        out.write("[properties]\nneeds_exe_wrapper = true\n\n[built-in options]\n")
        for language in ('c', 'cpp', 'objc', 'objcpp'):
            out.write(f"{language}_args = {flags!r}\n{language}_link_args = {link!r}\n")
        out.write(f"\n[binaries]\nc = ['{cc}']\ncpp = ['{cxx}']\nobjc = ['{cc}']\nobjcpp = ['{cxx}']\n"
                  "ar = ['ar']\nnm = ['nm']\nranlib = ['ranlib']\nstrip = ['strip', '-x']\n"
                  "pkg-config = ['pkg-config']\npython = ['python3']\n\n"
                  f"[host_machine]\n{system}\ncpu_family = 'aarch64'\ncpu = 'arm64'\nendian = 'little'\n")
PY
python3 - "$SOURCES/libepoxy/src/dispatch_common.c" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
old = '#define EGL_LIB "@rpath/MesaEGL.framework/MesaEGL"'
new = '#define EGL_LIB "@rpath/libEGL.framework/libEGL"'
if text.count(old) == 1:
    path.write_text(text.replace(old, new))
elif text.count(new) != 1:
    raise SystemExit("libepoxy provider line not found")
PY
export PKG_CONFIG_PATH= PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
meson setup "$BUILD/epoxy" "$SOURCES/libepoxy" --prefix "$PREFIX" --libdir lib \
  --buildtype release --cross-file "$BUILD/epoxy.cross" --wrap-mode=nodownload \
  -Ddefault_library=static -Dtests=false -Dglx=no -Degl=yes -Dx11=false
meson compile -C "$BUILD/epoxy" -j 3
meson install -C "$BUILD/epoxy"
MESA="$SOURCES/mesa"; [ -d "$MESA" ] || MESA="$SOURCES/Mesa"
install -m 0644 "$MESA/src/gallium/drivers/zink/zink_interop_public.h" "$PREFIX/include/GL/"
install -m 0644 "$MESA/include/GL/mesa_glinterop.h" "$PREFIX/include/GL/"
meson setup "$BUILD/virgl" "$SOURCES/virglrenderer" --prefix "$PREFIX" --libdir lib \
  --buildtype release --cross-file "$BUILD/virgl.cross" --wrap-mode=nodownload \
  -Ddefault_library=static -Dtests=false -Dcheck-gl-errors=false -Dvideo=false \
  -Dplatforms=egl -Dvenus=false
meson compile -C "$BUILD/virgl" -j 3
meson install -C "$BUILD/virgl"
install -m 0644 "$SOURCES/virglrenderer/src/virgl_hw.h" "$PREFIX/include/virgl/virgl_hw.h"
rm -rf "$PREFIX/lib/pkgconfig" "$PREFIX/bin" "$PREFIX/include/GL/zink_interop_public.h"
cp -R "$ANGLE/include/EGL" "$ANGLE/include/KHR" "$PREFIX/include/"
cp -R "$ANGLE/ios/libEGL.framework" "$ANGLE/ios/libGLESv2.framework" "$PREFIX/Frameworks/"
for framework in libEGL libGLESv2; do
  otool -D "$PREFIX/Frameworks/$framework.framework/$framework" | tail -1
  xcrun vtool -show-build "$PREFIX/Frameworks/$framework.framework/$framework" | grep -E 'platform|minos'
done
ls -la "$PREFIX/lib" "$PREFIX/Frameworks"

stage "network dependency for the iOS device"
bash dependencies/prepare.sh --product ios-network
bash dependencies/build-ios-network.sh --platform ios

stage "accepted Android kernel bundle from the upstream release"
mkdir -p .build/kernel/artifacts
curl -fsSL --retry 3 -o "$WORK/kernel.tar.gz" \
  https://github.com/imxieyi/Kernarium/releases/download/1.0b9-beta/android-6.18-arm64-4k-20261111-6.18.60-mc2.tar.gz
tar -C .build/kernel/artifacts -xzf "$WORK/kernel.tar.gz"
ls .build/kernel/artifacts .build/kernel/artifacts/* | head -30

stage "configure the device Android runtime"
cmake --preset kernarium-ios-device-android

stage "build the device Android runtime"
# Upstream's architecture audit forbids the Virgl-only mode on a device; this
# experiment is exactly that, so only the runtime target is built.
cmake --build .build/kernarium-runtime-ios-device-android-4k --target KernariumRuntime -j 4 -- -k 0
RUNTIME=$(find .build/kernarium-runtime-ios-device-android-4k -maxdepth 4 -name '*.framework' | head -1)
ls -la "$RUNTIME"
BINARY="$RUNTIME/$(basename "$RUNTIME" .framework)"
xcrun vtool -show-build "$BINARY" | grep -E 'platform|minos'
otool -L "$BINARY"
echo "Device runtime framework built for iOS 18 (not yet packaged into an app)."

stage "compression framework"
bash dependencies/prepare.sh --product ios-compression
bash dependencies/build-ios-zstd.sh

stage "package frameworks for the app"
OUT="$UPSTREAM/.build/kernarium-xcframeworks"
rm -rf "$OUT"; mkdir -p "$OUT"
cp -R "$RUNTIME" "$WORK/$(basename "$RUNTIME")"
strip -S "$WORK/$(basename "$RUNTIME")/$(basename "$RUNTIME" .framework)"
xcodebuild -create-xcframework -framework "$WORK/$(basename "$RUNTIME")" \
  -output "$OUT/KRuntime_Android_6_18_4K.xcframework"
for framework in libEGL libGLESv2; do
  ls -la "$PREFIX/Frameworks/$framework.framework"
  xcodebuild -create-xcframework -framework "$PREFIX/Frameworks/$framework.framework" \
    -output "$OUT/$framework.xcframework"
done
cp -R .build/dependencies/ios-zstd/LibZstd.xcframework "$OUT/"
du -sh "$OUT"/*
tar -C "$UPSTREAM/.build" -czf "$WORK/engine-ios18.tar.gz" kernarium-xcframeworks
ls -la "$WORK/engine-ios18.tar.gz"
echo "Frameworks packaged for the iOS 18 app build."
