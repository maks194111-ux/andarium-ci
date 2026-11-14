#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Retarget Andarium's build system at iOS 18 with ANGLE as the host GL.

Experiment. Three changes to a pristine upstream checkout:
  1. the deployment floor 27.0 becomes 18.0 in the toolchain and the
     dependency build scripts;
  2. the iOS device GPU product becomes the Virgl-only variant upstream uses
     for the Simulator, with ANGLE's libEGL/libGLESv2 frameworks in place of
     Mesa's (no KosmicKrisp, no guest Vulkan);
  3. upstream's provenance verification of the GPU prefix is not run, because
     this prefix is not one of upstream's products.  The step is replaced by a
     message that says so.
Every replacement must match exactly, or the script fails.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])


def edit(relative: str, replacements: list[tuple[str, str, int]]) -> None:
    path = root / relative
    text = path.read_text()
    for old, new, count in replacements:
        found = text.count(old)
        if found != count:
            raise SystemExit(f"{relative}: expected {count} of {old[:60]!r}, found {found}")
        text = text.replace(old, new)
    path.write_text(text)


# 1. Deployment floor.
edit("cmake/toolchains/Apple.cmake",
     [("set(_uml_apple_deployment_target 27.0)", "set(_uml_apple_deployment_target 18.0)", 1)])
for script in ("dependencies/build-ios-network.sh", "dependencies/ios-static-xcframework.sh"):
    edit(script, [("DEPLOYMENT_TARGET=27.0", "DEPLOYMENT_TARGET=18.0", 1)])

# The prefix verifiers and platform contracts name the same floor.
floor_files = sorted((root / "dependencies/cmake").glob("*.cmake")) + \
    sorted((root / "dependencies/platforms").glob("ios-*.tsv"))
changed = 0
for floor_file in floor_files:
    floor_text = floor_file.read_text()
    if "27.0" in floor_text:
        floor_file.write_text(floor_text.replace("27.0", "18.0"))
        changed += 1
if changed == 0:
    raise SystemExit("no deployment floor found in the prefix verifiers")
print(f"deployment floor rewritten in {changed} verifier and contract files")

# 2 and 3. GPU product.
path = root / "dependencies/cmake/AppleGpuDependencies.cmake"
text = path.read_text()


def replace(old: str, new: str, count: int = 1) -> None:
    global text
    found = text.count(old)
    if found != count:
        raise SystemExit(f"AppleGpuDependencies: expected {count} of {old[:60]!r}, found {found}")
    text = text.replace(old, new)


replace('''        "${PROJECT_SOURCE_DIR}/.build/dependencies/apple-gpu-vulkan-experiment/ios-device-arm64")
''', '''        "${PROJECT_SOURCE_DIR}/.build/dependencies/apple-gpu-vulkan-experiment/ios-device-arm64")
    # iOS 18 experiment: ANGLE on Metal serves Virgl; no Vulkan driver.
    set(_uml_apple_gpu_software TRUE)
''')
replace("set(_uml_apple_gl_frameworks MesaEGL MesaGallium)",
        "set(_uml_apple_gl_frameworks libEGL libGLESv2)")
verify = re.compile(
    r'execute_process\(\n    COMMAND "\$\{CMAKE_COMMAND\}"\n(?:        .*\n)+?    COMMAND_ERROR_IS_FATAL ANY\)\n')
if len(verify.findall(text)) != 1:
    raise SystemExit("AppleGpuDependencies: configure-time verification not found")
text = verify.sub(
    'message(WARNING "iOS 18 experiment: the ANGLE GPU prefix is not an upstream product; '
    'its provenance verification is not run.")\n', text)
target = re.compile(
    r'add_custom_target\(uml_apple_gpu_prefix_verify\n    COMMAND "\$\{CMAKE_COMMAND\}"\n(?:        .*\n)+?    DEPENDS')
if len(target.findall(text)) != 1:
    raise SystemExit("AppleGpuDependencies: build-time verification not found")
text = target.sub(
    'add_custom_target(uml_apple_gpu_prefix_verify\n'
    '    COMMAND "${CMAKE_COMMAND}" -E echo "ANGLE GPU prefix: upstream verification not run"\n'
    '    DEPENDS', text)
path.write_text(text)

# The engine sources: provider and the unsupported-interop answer.
gpu = root / "darwin/device/gpu/CMakeLists.txt"
gpu_text = gpu.read_text()
old = "    host_gl_provider.cpp\n    virgl_renderer.cpp)"
if gpu_text.count(old) != 1:
    raise SystemExit("gpu CMakeLists: renderer sources not found")
gpu.write_text(gpu_text.replace(
    old, "    angle_interop_unsupported.c\n    host_gl_provider.cpp\n    virgl_renderer.cpp)"))
print("build system retargeted: iOS 18.0, ANGLE host GL, Virgl only")
