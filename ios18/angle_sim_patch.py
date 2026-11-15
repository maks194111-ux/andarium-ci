#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Make the Simulator build of ANGLE use the Simulator's 256-byte buffer
offset alignment.

Metal in the iOS Simulator requires constant and argument buffer offsets to be
aligned to 256 bytes. ANGLE uses 4 (setBuffer) and 16 (GL_UNIFORM_BUFFER_OFFSET_
ALIGNMENT) on every non-macOS Apple target, which is right for a phone GPU but
makes SimMetalHost abort in -[AppleParavirtArgumentEncoder setBuffer:offset:
atIndex:]. Only the Simulator slice is changed; the device ANGLE build keeps
the native values.
"""
import sys
from pathlib import Path

PATCHES = {
    "src/libANGLE/renderer/metal/mtl_common.h": [(
        "// Alignment requirement for offset passed to setVertex|FragmentBuffer\n"
        "#if TARGET_OS_OSX || TARGET_OS_MACCATALYST\n",
        "// Alignment requirement for offset passed to setVertex|FragmentBuffer\n"
        "#if TARGET_OS_OSX || TARGET_OS_MACCATALYST || TARGET_OS_SIMULATOR\n",
    )],
    "src/libANGLE/renderer/metal/DisplayMtl.mm": [(
        "    if (supportsAppleGPUFamily(1))\n"
        "    {\n"
        "        mNativeCaps.uniformBufferOffsetAlignment =\n"
        "            16;",
        "    if (supportsAppleGPUFamily(1) && !TARGET_OS_SIMULATOR)\n"
        "    {\n"
        "        mNativeCaps.uniformBufferOffsetAlignment =\n"
        "            16;",
    )],
    # Simulator only: name any argument-buffer binding the Simulator's Metal
    # service would refuse, and leave it out, instead of losing the service.
    "src/libANGLE/renderer/metal/ProgramExecutableMtl.mm": [(
        "        [bufferEncoder.metalArgBufferEncoder setBuffer:mtlBuffer->get()\n",
        "        if (offset >= mtlBuffer->size())\n"
        "        {\n"
        "            NSLog(@\"Andarium ANGLE UBO: block %u slot %u offset %zu length %zu\",\n"
        "                  bufferIndex, actualBufferIdx, offset, mtlBuffer->size());\n"
        "            continue;\n"
        "        }\n"
        "        [bufferEncoder.metalArgBufferEncoder setBuffer:mtlBuffer->get()\n",
    )],
}


def apply(root: Path):
    for relative, edits in PATCHES.items():
        path = root / relative
        text = path.read_text()
        for old, new in edits:
            if text.count(old) != 1:
                raise SystemExit(f"{relative}: expected exactly one match, found {text.count(old)}")
            text = text.replace(old, new)
        path.write_text(text)
        print(f"patched {relative}")


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
