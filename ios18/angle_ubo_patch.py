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

PROGRAM = "src/libANGLE/renderer/metal/ProgramExecutableMtl.mm"
POOL = "src/libANGLE/renderer/metal/mtl_buffer_pool.mm"
BUFFER = "src/libANGLE/renderer/metal/BufferMtl.mm"
EXTRA = {
    # A pool that starts at size 0 and is asked for 0 bytes would create a
    # zero-length (nil) Metal buffer: allocate at least one aligned unit.
    POOL: [(
        "    size_t sizeToAllocate = roundUp(sizeInBytes, mAlignment);\n",
        "    size_t sizeToAllocate = roundUp(std::max<size_t>(sizeInBytes, 1), mAlignment);\n",
    )],
    # A cached uniform conversion made at a smaller offset covers only the
    # blocks that existed below the buffer's end; an offset at or past the
    # end gets its own (zero-filled) conversion instead of a slice that
    # starts at the end of the converted buffer.
    BUFFER: [(
        "            if (buffer.offset.second <= offset.second &&\n"
        "                (offset.second - buffer.offset.second) % buffer.uniformBufferBlockSize == 0)\n",
        "            if (buffer.offset.second <= offset.second &&\n"
        "                (offset.second - buffer.offset.second) % buffer.uniformBufferBlockSize == 0 &&\n"
        "                (offset.second < size() || buffer.offset.second == offset.second))\n",
    )],
}
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


def edit(root: Path, relative: str, edits) -> None:
    path = root / relative
    text = path.read_text()
    for old, new in edits:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{relative}: expected exactly one match, found {count}:\n{old}")
        text = text.replace(old, new)
    path.write_text(text)
    print(f"patched {relative} (empty uniform buffers)")


def apply(root: Path) -> None:
    edit(root, PROGRAM, EDITS)
    for relative, edits in EXTRA.items():
        edit(root, relative, edits)


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
