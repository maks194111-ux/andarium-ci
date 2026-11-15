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
    # Simulator only: ANGLE turns texture swizzle off for every Simulator, so
    # formats the Android graphics bridge stores swizzled (A8 glyph atlases
    # held as R8) sample the wrong channel and text disappears. Use the
    # Metal swizzle whenever the Simulator's device reports the GPU family.
    "src/libANGLE/renderer/metal/DisplayMtl.mm#swizzle": [(
        "                            supportsEitherGPUFamily(3, 2) && !isSimulator);\n",
        "                            supportsEitherGPUFamily(3, 2));\n",
    )],
    # Simulator only: name any argument-buffer binding the Simulator's Metal
    # service would refuse, and leave it out, instead of losing the service.
    "src/libANGLE/renderer/metal/ProgramExecutableMtl.mm": [(
        "#include <array>\n",
        "#include <array>\n#include <mutex>\n#include <set>\n",
    ), (
        # Diagnostics: the layout each uniform argument encoder reflects...
        "        encoder->argumentIndicesKnown = true;\n",
        "        for (MTLStructMember *member in reflection.bufferStructType.members)\n"
        "        {\n"
        "            NSLog(@\"Andarium ANGLE UBO layout %p %@: %@ index %lu type %lu array %lu offset %lu\",\n"
        "                  (__bridge void *)encoder->metalArgBufferEncoder.get(), function.name, member.name,\n"
        "                  (unsigned long)member.argumentIndex, (unsigned long)member.dataType,\n"
        "                  (unsigned long)(member.arrayType ? member.arrayType.arrayLength : 0),\n"
        "                  (unsigned long)member.offset);\n"
        "        }\n"
        "        encoder->argumentIndicesKnown = true;\n",
    ), (
        "        [bufferEncoder.metalArgBufferEncoder setBuffer:mtlBuffer->get()\n",
        "        if (offset >= mtlBuffer->size())\n"
        "        {\n"
        "            NSLog(@\"Andarium ANGLE UBO: block %u slot %u offset %zu length %zu\",\n"
        "                  bufferIndex, actualBufferIdx, offset, mtlBuffer->size());\n"
        "            continue;\n"
        "        }\n"
        "        {\n"
        "            // ...and, once per encoder and slot, the binding about to be encoded.\n"
        "            static auto *sLogMutex = new std::mutex();\n"
        "            static auto *sLogged   = new std::set<std::pair<const void *, uint32_t>>();\n"
        "            std::lock_guard<std::mutex> lock(*sLogMutex);\n"
        "            const void *key = (__bridge const void *)bufferEncoder.metalArgBufferEncoder.get();\n"
        "            if (sLogged->insert({key, actualBufferIdx}).second)\n"
        "            {\n"
        "                NSLog(@\"Andarium ANGLE UBO encode %p slot %u block %u offset %zu length %zu\",\n"
        "                      key, actualBufferIdx, bufferIndex, offset, mtlBuffer->size());\n"
        "            }\n"
        "        }\n"
        "        [bufferEncoder.metalArgBufferEncoder setBuffer:mtlBuffer->get()\n",
    )],
}


def apply(root: Path):
    for relative, edits in PATCHES.items():
        path = root / relative.split("#")[0]
        text = path.read_text()
        for old, new in edits:
            if text.count(old) != 1:
                raise SystemExit(f"{relative}: expected exactly one match, found {text.count(old)}")
            text = text.replace(old, new)
        path.write_text(text)
        print(f"patched {relative}")


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
