#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Write the frames the windowless Mac display mirrors to a file, as they come.

The engine's frame mirror (frame_tap.hpp) renders the guest's latest frame into
a small pixel buffer at a bounded rate; upstream uses it for Picture in
Picture.  With UML_FRAME_RECORD=<file> in the environment, each mirrored frame
is appended to that file with the host's monotonic time, but only while
<file>.on exists, so a test chooses what it records.  The video made from the
file shows every frame at the time it arrived: a stall is a still picture of
the same length, and nothing is interpolated.

The record is a sequence of
    u64 nanoseconds, u32 width, u32 height, u32 bytes per row, u32 packed size
followed by the pixels (BGRA): an LZ4 block of `packed size` bytes, or the raw
rows when the packed size is 0.

Compressing a frame costs host processor time on the machine that also runs
the guest, so a recorded run is, if anything, slower than an unrecorded one.
Mac test executable only; the phone build is not touched.

Usage: frame_record_patch.py <upstream root>
"""
import sys
from pathlib import Path

path = Path(sys.argv[1]) / "darwin/device/gpu/offscreen_display.mm"
text = path.read_text()


def replace(old: str, new: str) -> None:
    global text
    if text.count(old) != 1:
        raise SystemExit(f"offscreen_display.mm: expected one match for {old[:50]!r}, found {text.count(old)}")
    text = text.replace(old, new)


replace("#include <atomic>\n#include <cstdio>\n",
        "#include <atomic>\n#include <chrono>\n#include <cstdint>\n#include <cstdio>\n#include <cstdlib>\n"
        "#include <string>\n#include <vector>\n\n#include <dlfcn.h>\n#include <unistd.h>\n")

replace("""class MirrorHold final {
public:
""", """using FrameRecordEncode = std::size_t (*)(
    std::uint8_t*, std::size_t, const std::uint8_t*, std::size_t, void*, int);

struct FrameRecorder final {
    std::FILE* file {};
    std::string gate;
    FrameRecordEncode encode {};
    std::vector<std::uint8_t> packed;
    std::mutex mutex;
};

struct FrameRecordHeader final {
    std::uint64_t nanoseconds;
    std::uint32_t width;
    std::uint32_t height;
    std::uint32_t bytesPerRow;
    std::uint32_t packedSize;
};

/* CI recording of the mirrored frames (UML_FRAME_RECORD). */
void recordMirroredFrame(CVPixelBufferRef frame) noexcept
{
    static FrameRecorder* const recorder = []() -> FrameRecorder* {
        const char* const target = std::getenv("UML_FRAME_RECORD");
        if (target == nullptr || *target == '\\0')
            return nullptr;
        std::FILE* const file = std::fopen(target, "wb");
        if (file == nullptr) {
            std::fprintf(stderr, "Frame record: cannot open %s\\n", target);
            return nullptr;
        }
        auto* const created = new FrameRecorder;
        created->file = file;
        created->gate = std::string(target) + ".on";
        if (void* const library =
                ::dlopen("/usr/lib/libcompression.dylib", RTLD_NOW)) {
            created->encode = reinterpret_cast<FrameRecordEncode>(
                ::dlsym(library, "compression_encode_buffer"));
        }
        std::fprintf(
            stderr, "Frame record: %s, packing %s\\n", target,
            created->encode != nullptr ? "LZ4" : "none");
        return created;
    }();
    if (recorder == nullptr || ::access(recorder->gate.c_str(), F_OK) != 0)
        return;
    const auto now = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
    if (CVPixelBufferLockBaseAddress(frame, kCVPixelBufferLock_ReadOnly) !=
        kCVReturnSuccess)
        return;
    {
        std::lock_guard lock(recorder->mutex);
        const auto* const pixels = static_cast<const std::uint8_t*>(
            CVPixelBufferGetBaseAddress(frame));
        const std::size_t rowBytes = CVPixelBufferGetBytesPerRow(frame);
        const std::size_t rows = CVPixelBufferGetHeight(frame);
        const std::size_t size = rowBytes * rows;
        std::size_t packedSize = 0;
        if (pixels != nullptr && size != 0) {
            if (recorder->encode != nullptr) {
                recorder->packed.resize(size);
                /* 0x101 is COMPRESSION_LZ4_RAW: one plain LZ4 block. */
                packedSize = recorder->encode(
                    recorder->packed.data(), size, pixels, size, nullptr,
                    0x101);
            }
            const FrameRecordHeader header {
                .nanoseconds = static_cast<std::uint64_t>(now),
                .width = static_cast<std::uint32_t>(
                    CVPixelBufferGetWidth(frame)),
                .height = static_cast<std::uint32_t>(rows),
                .bytesPerRow = static_cast<std::uint32_t>(rowBytes),
                .packedSize = static_cast<std::uint32_t>(packedSize),
            };
            (void)std::fwrite(&header, sizeof header, 1, recorder->file);
            if (packedSize != 0)
                (void)std::fwrite(
                    recorder->packed.data(), 1, packedSize, recorder->file);
            else
                (void)std::fwrite(pixels, 1, size, recorder->file);
            (void)std::fflush(recorder->file);
        }
    }
    (void)CVPixelBufferUnlockBaseAddress(frame, kCVPixelBufferLock_ReadOnly);
}

class MirrorHold final {
public:
""")

replace("""    void keep(CVPixelBufferRef frame)
    {
        std::lock_guard lock(mutex_);
""", """    void keep(CVPixelBufferRef frame)
    {
        recordMirroredFrame(frame);
        std::lock_guard lock(mutex_);
""")

path.write_text(text)
print("frame record: offscreen_display.mm patched")
