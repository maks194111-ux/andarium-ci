#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Never bind a missing Metal buffer for an empty uniform buffer.

When a program's uniform block is bound to a GL buffer with no data at the
bound offset (an empty buffer, or an offset at its end), ANGLE converts zero
blocks, asks its conversion pool (initial size 0) for 0 bytes and gets a Metal
buffer of length zero, which Metal refuses ("Cannot create buffer of zero
length"). The missing buffer is then written into the uniform argument buffer.
The iOS Simulator's Metal service aborts on that (-[AppleParavirtArgumentEncoder
setBuffer:offset:atIndex:]); on a device the shader reads through a null GPU
address. With this patch a conversion always holds at least one zero-filled
block, which is what a robust GL driver returns for reads past the data, and
the binding code skips a buffer that is still missing instead of encoding it.

Applied to the device and the Simulator builds of ANGLE alike.
"""
import sys
from pathlib import Path

FILE = "src/libANGLE/renderer/metal/ProgramExecutableMtl.mm"
EDITS = [
    (
        "    size_t numBlocksToCopy =\n"
        "        (sizeToCopy + blockConversionInfo.stdSize() - 1) / blockConversionInfo.stdSize();\n"
        "    size_t bytesToAllocate = numBlocksToCopy * blockConversionInfo.metalSize();\n"
        "    angle::Span<uint8_t> dst;\n"
        "    ANGLE_TRY(dynamicBuffer->allocateAndMap(contextMtl, bytesToAllocate, &dst, outBuffer));\n",
        "    // Andarium: at least one block, so an empty source never yields a\n"
        "    // zero-length (nil) Metal buffer; bytes past the source read as zero.\n"
        "    size_t numBlocksToCopy = std::max<size_t>(\n"
        "        1, (sizeToCopy + blockConversionInfo.stdSize() - 1) / blockConversionInfo.stdSize());\n"
        "    size_t bytesToAllocate = numBlocksToCopy * blockConversionInfo.metalSize();\n"
        "    angle::Span<uint8_t> dst;\n"
        "    ANGLE_TRY(dynamicBuffer->allocateAndMap(contextMtl, bytesToAllocate, &dst, outBuffer));\n"
        "    std::fill(dst.begin(), dst.end(), uint8_t{0});\n",
    ),
    (
        "        if (stages == 0)\n"
        "        {\n"
        "            continue;\n"
        "        }\n"
        "\n"
        "        cmdEncoder->useResource(mLegalizedOffsetedUniformBuffers[bufferIndex].buffer(),\n",
        "        if (stages == 0 || !mLegalizedOffsetedUniformBuffers[bufferIndex].buffer())\n"
        "        {\n"
        "            continue;\n"
        "        }\n"
        "\n"
        "        cmdEncoder->useResource(mLegalizedOffsetedUniformBuffers[bufferIndex].buffer(),\n",
    ),
    (
        "        mtl::BufferRef mtlBuffer = mLegalizedOffsetedUniformBuffers[bufferIndex].buffer();\n"
        "        size_t offset            = mLegalizedOffsetedUniformBuffers[bufferIndex].offset();\n"
        "        cmdEncoder->setBuffer(shaderType, mtlBuffer, offset, actualBufferIdx);\n",
        "        mtl::BufferRef mtlBuffer = mLegalizedOffsetedUniformBuffers[bufferIndex].buffer();\n"
        "        if (!mtlBuffer)\n"
        "        {\n"
        "            continue;\n"
        "        }\n"
        "        size_t offset            = mLegalizedOffsetedUniformBuffers[bufferIndex].offset();\n"
        "        cmdEncoder->setBuffer(shaderType, mtlBuffer, offset, actualBufferIdx);\n",
    ),
    (
        "        mtl::BufferRef mtlBuffer = mLegalizedOffsetedUniformBuffers[bufferIndex].buffer();\n"
        "        size_t offset            = mLegalizedOffsetedUniformBuffers[bufferIndex].offset();\n"
        "        [bufferEncoder.metalArgBufferEncoder setBuffer:mtlBuffer->get()\n",
        "        mtl::BufferRef mtlBuffer = mLegalizedOffsetedUniformBuffers[bufferIndex].buffer();\n"
        "        if (!mtlBuffer || !mtlBuffer->get())\n"
        "        {\n"
        "            continue;\n"
        "        }\n"
        "        size_t offset            = mLegalizedOffsetedUniformBuffers[bufferIndex].offset();\n"
        "        [bufferEncoder.metalArgBufferEncoder setBuffer:mtlBuffer->get()\n",
    ),
]


def apply(root: Path) -> None:
    path = root / FILE
    text = path.read_text()
    for old, new in EDITS:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{FILE}: expected exactly one match, found {count}:\n{old}")
        text = text.replace(old, new)
    path.write_text(text)
    print(f"patched {FILE} (empty uniform buffers)")


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
