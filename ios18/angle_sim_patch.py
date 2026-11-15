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
        "#include <array>\n#include <cstring>\n#include <mutex>\n#include <set>\n",
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
        # The Simulator's Metal service on a macOS 15 host cannot find the
        # arguments of an encoder made from the function ("Failed to find
        # buffer argument (0)") and aborts. Describe the same pointer layout
        # explicitly instead; keep it only if the encoded size is identical.
        "    ANGLE_APPLE_ALLOW_DEPRECATED_END\n"
        "    if (encoder->metalArgBufferEncoder)\n",
        "    if (encoder->metalArgBufferEncoder && reflection && reflection.bufferStructType)\n"
        "    {\n"
        "        NSMutableArray<MTLArgumentDescriptor *> *arguments = [NSMutableArray array];\n"
        "        bool describable = true;\n"
        "        for (MTLStructMember *member in reflection.bufferStructType.members)\n"
        "        {\n"
        "            MTLArgumentDescriptor *argument = [MTLArgumentDescriptor argumentDescriptor];\n"
        "            argument.index                  = member.argumentIndex;\n"
        "            argument.access                 = MTLBindingAccessReadOnly;\n"
        "            if (member.dataType == MTLDataTypePointer)\n"
        "            {\n"
        "                argument.dataType = MTLDataTypePointer;\n"
        "            }\n"
        "            else if (member.dataType == MTLDataTypeArray && member.arrayType &&\n"
        "                     member.arrayType.elementType == MTLDataTypePointer)\n"
        "            {\n"
        "                argument.dataType    = MTLDataTypePointer;\n"
        "                argument.arrayLength = member.arrayType.arrayLength;\n"
        "            }\n"
        "            else\n"
        "            {\n"
        "                describable = false;\n"
        "                break;\n"
        "            }\n"
        "            [arguments addObject:argument];\n"
        "        }\n"
        "        if (describable && arguments.count > 0)\n"
        "        {\n"
        "            angle::ObjCPtr<id<MTLArgumentEncoder>> described =\n"
        "                angle::adoptObjCPtr([function.device newArgumentEncoderWithArguments:arguments]);\n"
        "            const NSUInteger fromFunction = encoder->metalArgBufferEncoder.get().encodedLength;\n"
        "            const NSUInteger fromLayout   = described ? described.get().encodedLength : 0;\n"
        "            NSLog(@\"Andarium ANGLE UBO described encoder %@: %lu arguments, length %lu (function %lu)\",\n"
        "                  function.name, (unsigned long)arguments.count, (unsigned long)fromLayout,\n"
        "                  (unsigned long)fromFunction);\n"
        "            if (described && fromLayout == fromFunction)\n"
        "            {\n"
        "                encoder->metalArgBufferEncoder = std::move(described);\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "    // The iOS 18 Simulator's encoders report no layout (encoded length 0) and\n"
        "    // its Metal service then finds no argument to set: write each buffer's\n"
        "    // GPU address where the reflected struct keeps the pointer instead.\n"
        "    if (encoder->metalArgBufferEncoder && reflection && reflection.bufferStructType &&\n"
        "        encoder->metalArgBufferEncoder.get().encodedLength == 0)\n"
        "    {\n"
        "        encoder->rawAddresses = true;\n"
        "        encoder->rawLength    = std::max<size_t>(reflection.bufferDataSize, 8);\n"
        "        for (MTLStructMember *member in reflection.bufferStructType.members)\n"
        "        {\n"
        "            const NSUInteger count = member.arrayType ? member.arrayType.arrayLength : 1;\n"
        "            for (NSUInteger i = 0; i < count; ++i)\n"
        "            {\n"
        "                const NSUInteger index = member.argumentIndex + i;\n"
        "                if (index < 64)\n"
        "                {\n"
        "                    encoder->rawOffsets[index] = static_cast<uint32_t>(member.offset + 8 * i);\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "        NSLog(@\"Andarium ANGLE UBO raw addresses %@: length %zu\", function.name, encoder->rawLength);\n"
        "    }\n"
        "    ANGLE_APPLE_ALLOW_DEPRECATED_END\n"
        "    if (encoder->metalArgBufferEncoder)\n",
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
    ), (
        "        context, bufferEncoder.metalArgBufferEncoder.get().encodedLength, &argumentBuffer));\n",
        "        context,\n"
        "        bufferEncoder.rawAddresses ? bufferEncoder.rawLength\n"
        "                                   : bufferEncoder.metalArgBufferEncoder.get().encodedLength,\n"
        "        &argumentBuffer));\n",
    ), (
        "    ANGLE_UNUSED_VARIABLE(argumentBuffer.buffer()->mapNoSync(context));\n"
        "\n"
        "    [bufferEncoder.metalArgBufferEncoder setArgumentBuffer:argumentBuffer.buffer()->get()\n"
        "                                                    offset:argumentBuffer.offset()];\n",
        "    uint8_t *argumentBytes = argumentBuffer.buffer()->mapNoSync(context).data();\n"
        "\n"
        "    if (bufferEncoder.rawAddresses)\n"
        "    {\n"
        "        memset(argumentBytes + argumentBuffer.offset(), 0, bufferEncoder.rawLength);\n"
        "    }\n"
        "    else\n"
        "    {\n"
        "        [bufferEncoder.metalArgBufferEncoder setArgumentBuffer:argumentBuffer.buffer()->get()\n"
        "                                                        offset:argumentBuffer.offset()];\n"
        "    }\n",
    ), (
        "        [bufferEncoder.metalArgBufferEncoder setBuffer:mtlBuffer->get()\n"
        "                                                offset:offset\n"
        "                                               atIndex:actualBufferIdx];\n",
        "        if (bufferEncoder.rawAddresses)\n"
        "        {\n"
        "            if (actualBufferIdx < 64 &&\n"
        "                bufferEncoder.rawOffsets[actualBufferIdx] + sizeof(uint64_t) <= bufferEncoder.rawLength)\n"
        "            {\n"
        "                const uint64_t address = mtlBuffer->get().gpuAddress + offset;\n"
        "                memcpy(argumentBytes + argumentBuffer.offset() + bufferEncoder.rawOffsets[actualBufferIdx],\n"
        "                       &address, sizeof address);\n"
        "            }\n"
        "        }\n"
        "        else\n"
        "        {\n"
        "        [bufferEncoder.metalArgBufferEncoder setBuffer:mtlBuffer->get()\n"
        "                                                offset:offset\n"
        "                                               atIndex:actualBufferIdx];\n"
        "        }\n",
    ), (
        "        context, argumentBuffer.offset(), bufferEncoder.metalArgBufferEncoder.get().encodedLength);\n",
        "        context, argumentBuffer.offset(),\n"
        "        bufferEncoder.rawAddresses ? bufferEncoder.rawLength\n"
        "                                   : bufferEncoder.metalArgBufferEncoder.get().encodedLength);\n",
    )],
    "src/libANGLE/renderer/metal/ProgramExecutableMtl.h": [(
        "    bool argumentIndicesKnown     = false;\n",
        "    bool argumentIndicesKnown     = false;\n"
        "    // Andarium (Simulator): pointers written as GPU addresses, not encoded.\n"
        "    bool rawAddresses             = false;\n"
        "    size_t rawLength              = 0;\n"
        "    uint32_t rawOffsets[64]       = {};\n",
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
