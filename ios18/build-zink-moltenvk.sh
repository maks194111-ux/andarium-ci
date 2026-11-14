#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Isolated compatibility experiment, not an accepted production prefix.
set -euo pipefail
UPSTREAM=$(cd "$1" && pwd)
WORK=$(cd "$2" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
DRIVER="$WORK/MoltenVK/MoltenVK"
SOURCES="$WORK/sources"
PREFIX="$WORK/zink-prefix"

# Preserve the paired host/guest Mesa patch history; never substitute stock Mesa.
bash "$UPSTREAM/dependencies/prepare.sh" \
  --product apple-gpu-vulkan-experiment --root "$SOURCES" --cache "$WORK/source-cache"
bash "$UPSTREAM/dependencies/prepare.sh" \
  --product apple-gpu-vulkan-experiment --root "$SOURCES" --verify

# MoltenVK has no robustness2.nullDescriptor; restore real placeholder resources.
python3 "$HERE/zink_null_descriptor_fallback.py" "$SOURCES/mesa"

# Keep generated grammar tools and packages separate from runtime libraries.
mkdir -p "$WORK/empty-pkgconfig" "$WORK/grammar-tools"
BISON=$(command -v bison)
case "$("$BISON" --version | head -1)" in
  *" 2."*)
    sed "s|@BISON@|$BISON|g" "$UPSTREAM/dependencies/bison2-grammar-shim.sh" \
      > "$WORK/grammar-tools/bison"
    chmod +x "$WORK/grammar-tools/bison"
    ;;
esac
export PATH="$WORK/grammar-tools:$PATH"
export PKG_CONFIG_PATH=
export PKG_CONFIG_LIBDIR="$WORK/empty-pkgconfig"
export SDKROOT="$(xcrun --sdk macosx --show-sdk-path)"
export MACOSX_DEPLOYMENT_TARGET=15.0
export CC="$(xcrun --find clang)" CXX="$(xcrun --find clang++)"
export OBJC="$CC" OBJCXX="$CXX"

xcrun clang++ -std=c++17 -Wall -Wextra -Werror -fsyntax-only \
  -I "$SOURCES/mesa/include" "$HERE/egl-probe.cpp"

python3 -m mesonbuild.mesonmain setup "$WORK/zink-build" "$SOURCES/mesa" \
  --prefix "$PREFIX" --libdir lib --buildtype release --wrap-mode=nodownload \
  -Dplatforms=macos -Dvulkan-drivers= -Dgallium-drivers=zink \
  -Dmoltenvk-dir="$WORK/MoltenVK" \
  -Dzink-vulkan-library-file="$DRIVER/dynamic/dylib/macOS/libMoltenVK.dylib" \
  -Dopengl=true -Degl=enabled -Dglx=disabled -Dgles1=disabled -Dgles2=disabled \
  -Dzstd=disabled -Dllvm=disabled -Dspirv-tools=disabled -Ddebug=true
python3 -m mesonbuild.mesonmain compile -C "$WORK/zink-build" -j 3
python3 -m mesonbuild.mesonmain install --no-rebuild -C "$WORK/zink-build"

xcrun clang++ -std=c++17 -Wall -Wextra -Werror \
  -I "$PREFIX/include" "$HERE/egl-probe.cpp" -L "$PREFIX/lib" -lEGL \
  -Wl,-rpath,"$PREFIX/lib" -Wl,-rpath,"$DRIVER/dynamic/dylib/macOS" \
  -o "$WORK/egl-probe"

# A hung driver is an explicit failed test, not an indefinite runner charge.
export GALLIUM_DRIVER=zink MESA_LOADER_DRIVER_OVERRIDE=zink
unset LIBGL_ALWAYS_SOFTWARE MESA_GL_VERSION_OVERRIDE MESA_GLES_VERSION_OVERRIDE
python3 - "$WORK/egl-probe" <<'PY'
import subprocess
import sys
subprocess.run([sys.argv[1]], check=True, timeout=90)
PY
