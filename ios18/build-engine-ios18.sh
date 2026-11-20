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

# The newer engine tree: ahead-of-time code for the system libraries.
NEWUP=${NEWUP:-0}
if [ "$NEWUP" = 1 ]; then
  stage "EROFS reader with Zstandard (the ahead-of-time tool needs it)"
  for tool in zstd lz4 xz; do HOMEBREW_NO_AUTO_UPDATE=1 brew list "$tool" >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install "$tool"; done
  git clone -q --depth=1 -b v1.8.6 https://github.com/erofs/erofs-utils.git "$WORK/erofs-utils"
  BREW=$(brew --prefix)
  # macOS has no getrandom(); the reader's identifier helper gets its bytes from getentropy().
  sed -i '' 's/r = getrandom(out, size, flags);/r = getentropy(out, size) == 0 ? (int)size : -1; (void)flags;/' "$WORK/erofs-utils/lib/uuid.c"
  grep -c getentropy "$WORK/erofs-utils/lib/uuid.c" >/dev/null || { echo "RESULT: the EROFS reader source changed."; exit 1; }
  ( cd "$WORK/erofs-utils" && { ./autogen.sh && \
    PKG_CONFIG_PATH="$BREW/lib/pkgconfig:$BREW/opt/zstd/lib/pkgconfig:$BREW/opt/lz4/lib/pkgconfig:$BREW/opt/xz/lib/pkgconfig" \
    CPPFLAGS="-I$BREW/include" LDFLAGS="-L$BREW/lib" \
    ./configure --with-libzstd --disable-fuse --without-uuid && \
    make -j 4; } > "$WORK/erofs-build.log" 2>&1 ) || { tail -40 "$WORK/erofs-build.log"; echo "RESULT: the EROFS reader could not be built."; exit 1; }
  FSCK_EROFS="$WORK/erofs-utils/fsck/fsck.erofs"
  EROFS_HELP=$("$FSCK_EROFS" --help 2>&1 || true)
  case "$EROFS_HELP" in *zstd*) echo "EROFS reader built with Zstandard";; *) echo "$EROFS_HELP"; echo "RESULT: the EROFS reader has no Zstandard."; exit 1;; esac
fi
fetch_sources() {
  # Source servers answer 5xx at times; the sources are pinned by commit.
  for attempt in 1 2 3 4 5 6; do bash dependencies/prepare.sh --product "$1" && return 0; sleep 45; done
  return 1
}

cd "$UPSTREAM"
stage "test native address reservation fallback"
python3 "$HERE/test_window_patch.py" "$UPSTREAM"
stage "retarget build system"
python3 "$HERE/engine_build_patch.py" "$UPSTREAM"
python3 "$HERE/angle_provider.py" "$UPSTREAM"
if [ "$NEWUP" = 1 ]; then
  # The newer sources call iOS 26/27 interfaces unguarded; this build is for a device on iOS 27.
  sed -i '' 's/-Wall;-Wextra;-Werror>/-Wall;-Wextra;-Werror;-Wno-error=unguarded-availability-new>/' CMakeLists.txt
  grep -c 'Wno-error=unguarded-availability-new' CMakeLists.txt >/dev/null || { echo "RESULT: warning policy line not found."; exit 1; }
fi
python3 "$HERE/engine_api_patch.py" "$UPSTREAM"
python3 "$HERE/refresh_patch.py" "$UPSTREAM" engine
python3 "$HERE/angle_scanout.py" "$UPSTREAM"
python3 "$HERE/async_scanout_patch.py" "$UPSTREAM"
if [ "${FENCE_WAKE_EXPERIMENT:-0}" = 1 ]; then python3 "$HERE/fence_wakeup_patch.py" "$UPSTREAM"; fi
python3 "$HERE/qos_patch.py" "$UPSTREAM" engine
# The fast clock path names addresses of one kernel build; measured as no gain.
[ "$NEWUP" = 1 ] || python3 "$HERE/fastclock_patch.py" "$UPSTREAM"
python3 "$HERE/window_patch.py" "$UPSTREAM"
python3 "$HERE/memfit_patch.py" "$UPSTREAM"
stage "presentation metrics and opt-in adaptive pacing"
c++ -std=c++20 -O2 -pthread "$HERE/test_frame_delivery_metrics.cpp" -o "$WORK/test-frame-delivery"
"$WORK/test-frame-delivery"
python3 "$HERE/display_pacing_patch.py" "$UPSTREAM"
python3 "$HERE/presentation_metrics_patch.py" "$UPSTREAM"
python3 "$HERE/diagnostics_patch.py" "$UPSTREAM" engine

stage "GPU prefix: libepoxy and virglrenderer for arm64 iOS 18 on ANGLE"
fetch_sources apple-gpu-vulkan-experiment
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
python3 "$HERE/virgl_gles_patch.py" "$SOURCES/virglrenderer"
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
fetch_sources ios-network
bash dependencies/build-ios-network.sh --platform ios

stage "accepted Android kernel bundle from the upstream release"
mkdir -p .build/kernel/artifacts
AOT_FLAGS=()
if [ "$NEWUP" = 1 ]; then
  # Kernel built from the engine source's own scripts at the commit under test.
  [ -f "${KERNEL_TARBALL:-}" ] || { echo "RESULT: no kernel build was provided."; exit 1; }
  tar -C .build/kernel/artifacts -xzf "$KERNEL_TARBALL"
  # The release string ends in the commit of the replayed patch series; a
  # replay elsewhere makes the same tree under another commit.
  BUILT_RELEASE=$(cat .build/kernel/artifacts/*/kernel/kernel.release)
  echo "kernel release built here: $BUILT_RELEASE"
  sed -i '' "s|^UML_KERNEL_ARTIFACT_RELEASE=.*|UML_KERNEL_ARTIFACT_RELEASE='$BUILT_RELEASE'|" kernel/mainline-6.18/artifacts/accepted-android-4k.env
  # A compiler may place the allowance rule differently; then the window
  # keeps upstream's size and the memory fit below chooses what the device grants.
  python3 "$HERE/kernel_window_patch.py" "$UPSTREAM" .build/kernel/artifacts/* || echo "NOTE: address window allowance left as upstream has it"

  stage "ahead-of-time code for the image the app will carry"
  mkdir -p .build/android/releases
  curl -fsSL --retry 3 -o "$WORK/release.tar.gz" \
    https://github.com/imxieyi/Kernarium/releases/download/1.0b15-release/lineage24-mainline6.18-4k-20261115-los24-r28.tar.gz
  tar -C .build/android/releases -xzf "$WORK/release.tar.gz"; rm -f "$WORK/release.tar.gz"
  STOCK=$(ls -d "$UPSTREAM"/.build/android/releases/*/ | head -1); STOCK=${STOCK%/}
  [ -n "${GAPPS_FIX9_IPA_URL:-}" ] || { echo "RESULT: no package address was provided."; exit 1; }
  curl -fsSL --retry 3 -o "$WORK/gapps.ipa" "$GAPPS_FIX9_IPA_URL" 2>/dev/null || { echo "RESULT: the package could not be fetched."; exit 1; }
  base="$WORK/release-google-base"; cp -R "$STOCK" "$base"
  for entry in release-manifest.json boot/kernel-command-line.txt guest/partition-layout.json guest/system.img; do
    unzip -p "$WORK/gapps.ipa" "Payload/Andarium.app/andarium-system/$entry" > "$base/$entry"
  done
  rm -f "$WORK/gapps.ipa"
  AOT_TARGET="$WORK/release-aot"
  python3 "$HERE/sf_pipeline/splice_odm.py" "$base" "$AOT_TARGET" "$HERE/sf_pipeline/odm-bgquiet.img" || { echo "RESULT: the odm partition could not be replaced."; exit 1; }
  rm -rf "$base"
  AOT_CAPACITY=()
  if [ "${AOT_EXTRA:-1}" = 1 ]; then python3 "$HERE/aot_list_patch.py" "$UPSTREAM"; AOT_CAPACITY=(-DUML_AOT_INSTANCE_CAPACITY=8192); fi
  python3 tools/aot/release_artifact.py build --release "$AOT_TARGET" --fsck-erofs "$FSCK_EROFS" --out "$WORK/aot-artifact" --jobs 4 \
    || { echo "RESULT: the ahead-of-time code could not be built for this image."; exit 1; }
  ls -la "$WORK/aot-artifact"; cat "$WORK/aot-artifact/artifact.json" | head -30
  shasum -a 256 "$AOT_TARGET/release-manifest.json" "$AOT_TARGET/guest/system.img"
  rm -rf "$AOT_TARGET"
  AOT_FLAGS=(-DUML_AOT_MODE=ON "-DUML_AOT_ARTIFACT=$WORK/aot-artifact" ${AOT_CAPACITY[@]+"${AOT_CAPACITY[@]}"})
else
curl -fsSL --retry 3 -o "$WORK/kernel.tar.gz" \
  https://github.com/imxieyi/Kernarium/releases/download/1.0b9-beta/android-6.18-arm64-4k-20261111-6.18.60-mc2.tar.gz
tar -C .build/kernel/artifacts -xzf "$WORK/kernel.tar.gz"
python3 "$HERE/kernel_window_patch.py" "$UPSTREAM" .build/kernel/artifacts/*
python3 "$HERE/fastclock_patch.py" --check .build/kernel/artifacts/*/kernel/System.map
fi
ls .build/kernel/artifacts .build/kernel/artifacts/* | head -30

stage "configure the device Android runtime"
cmake --preset kernarium-ios-device-android ${AOT_FLAGS[@]+"${AOT_FLAGS[@]}"}

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
fetch_sources ios-compression
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
if [ "$NEWUP" = 1 ]; then
  otool -L "$BINARY" | grep UmlArm64Aot || { echo "RESULT: the runtime does not link the ahead-of-time code."; exit 1; }
  AOTFW=$(find .build/kernarium-runtime-ios-device-android-4k -maxdepth 4 -name 'UmlArm64Aot.framework' | head -1)
  [ -d "$AOTFW" ] || { echo "RESULT: the ahead-of-time framework was not built."; exit 1; }
  ls -la "$AOTFW"; xcrun vtool -show-build "$AOTFW/UmlArm64Aot" | grep -E 'platform|minos'
  xcodebuild -create-xcframework -framework "$AOTFW" -output "$OUT/UmlArm64Aot.xcframework"
fi
du -sh "$OUT"/*
tar -C "$UPSTREAM/.build" -czf "$WORK/engine-ios18.tar.gz" kernarium-xcframeworks
ls -la "$WORK/engine-ios18.tar.gz"
echo "Frameworks packaged for the iOS 18 app build."
