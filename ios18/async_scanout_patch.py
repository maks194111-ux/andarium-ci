#!/usr/bin/env python3
"""Replace the per-frame CPU finish with a Metal queue dependency.

Run after angle_scanout.py, before diagnostics_patch.py. The synchronous
control remains selectable; texture leases protect both display and mirror.
"""
import sys
from pathlib import Path

gpu = Path(sys.argv[1]) / "darwin/device/gpu"


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise SystemExit(f"async scanout: expected {count} occurrences of {old[:80]!r}, got {text.count(old)}")
    return text.replace(old, new)


header = gpu / "angle_scanout.hpp"
text = header.read_text()
text = replace(text, "#include <cstdint>", "#include <cstdint>\n#include <memory>")
text = replace(text, "} // namespace uml::gpu", """
// An opaque lease owns the frame until every Metal consumer has completed.
// Capture it under the presentation mutex with the corresponding texture.
using AngleFrameLease = std::shared_ptr<void>;
[[nodiscard]] AngleFrameLease angleScanoutLease(void* texture) noexcept;
void angleScanoutEncodeWait(void* commands, const AngleFrameLease& lease) noexcept;
} // namespace uml::gpu""")
header.write_text(text)

path = gpu / "angle_scanout.mm"
text = path.read_text()
text = replace(text, "#include <cstring>", "#include <cstring>\n#include <memory>\n#include <mutex>")
text = replace(text, "struct Slot {", """
struct Frame {
    id<MTLTexture> texture;
    id<MTLSharedEvent> ready;
    std::uint64_t value {};
};

struct Slot {""")
text = replace(text, "    GLuint texture {};", """    GLuint texture {};
    id<MTLSharedEvent> ready;
    std::uint64_t value {};
    std::weak_ptr<Frame> leased;""")
text = replace(text, "    std::size_t next {};", """    std::size_t next {};
    std::mutex leaseMutex;
    std::shared_ptr<Frame> publishing;
    bool asyncSupported {};
    std::uint64_t asyncFrames {};
    std::uint64_t syncFrames {};
    std::uint64_t busyFrames {};""")
text = replace(text, "        slot = {};", "        slot = {};")
text = replace(text, "            slot.metal = [s.device newTextureWithDescriptor:descriptor];",
"""            slot.metal = [s.device newTextureWithDescriptor:descriptor];
            slot.ready = [s.device newSharedEvent];""")
text = replace(text, "    s.width = width;", """    s.width = width;""")
text = replace(text, "    if (!s.usable)\n        return nullptr;", """    if (!s.usable)
        return nullptr;
    // The previous publication has either acquired a display lease or was
    // refused. A refused frame must not keep a slot occupied indefinitely.
    {
        std::lock_guard lock(s.leaseMutex);
        s.publishing.reset();
    }""")
text = replace(text, "        s.usable = offered && !disabled && s.device != nil;", """        s.usable = offered && !disabled && s.device != nil;
        s.asyncSupported = extensions != nullptr &&
            std::strstr(extensions, "EGL_ANGLE_metal_shared_event_sync") != nullptr;
        std::fprintf(stderr, "ANGLE async scanout: shared event %s\\n",
            s.asyncSupported ? "available" : "unavailable, synchronous fallback");""")
text = replace(text, "    auto& slot = s.ring[s.next];", """    // Do not overwrite a texture still held by the window or mirror.
    // Bounded ring: if every slot is in use, take the existing CPU fallback,
    // never grow a FIFO, busy-spin, or overwrite a consumer's frame.
    std::size_t selected = kRingSize;
    {
        std::lock_guard lock(s.leaseMutex);
        for (std::size_t offset = 0; offset < kRingSize; ++offset) {
            const auto index = (s.next + offset) % kRingSize;
            if (s.ring[index].leased.expired()) {
                selected = index;
                break;
            }
        }
    }
    if (selected == kRingSize) {
        if (++s.busyFrames == 1)
            std::fputs("ANGLE async scanout: ring busy, safe readback fallback\\n", stderr);
        return nullptr;
    }
    auto& slot = s.ring[selected];""")
text = replace(text, """    // The display samples the texture from its own Metal queue; the copy has
    // to be complete before that, and Metal orders nothing across queues.
    glFinish();""", """    // Queue-to-queue dependency: ANGLE signals after the copy; each Metal
    // consumer waits on the GPU before sampling. No CPU wait on this path.
    // Runtime control permits alternating A/B inside one settled guest boot.
    bool asynchronous = s.asyncSupported && slot.ready != nil;
    if (const char* control = std::getenv("UML_ANGLE_ASYNC_CONTROL")) {
        if (FILE* in = std::fopen(control, "r")) {
            asynchronous = asynchronous && std::fgetc(in) == '1';
            std::fclose(in);
        } else {
            asynchronous = false; // missing control is the synchronous control
        }
    }
    if (const char* value = std::getenv("UML_ANGLE_ASYNC"))
        asynchronous = asynchronous && std::strcmp(value, "0") != 0;
    std::shared_ptr<Frame> frame;
    try {
        frame = std::make_shared<Frame>();
    } catch (...) {
        glFinish();
        return nullptr;
    }
    frame->texture = slot.metal;
    if (asynchronous) {
        const auto value = ++slot.value;
        // EGLAttrib is pointer-sized; EGLint attributes would truncate the
        // MTLSharedEvent pointer on arm64.
        const EGLAttrib attributes[] {
            0x34D9, reinterpret_cast<EGLAttrib>((__bridge void*)slot.ready),
            0x34DA, static_cast<EGLAttrib>(value & 0xffffffffULL),
            0x34DB, static_cast<EGLAttrib>(value >> 32),
            EGL_NONE,
        };
        EGLSync sync = eglCreateSync(s.display, 0x34D8, attributes);
        if (sync != EGL_NO_SYNC) {
            frame->ready = slot.ready;
            frame->value = value;
            glFlush();
            eglDestroySync(s.display, sync);
            ++s.asyncFrames;
        } else {
            std::fprintf(stderr, "ANGLE async scanout: EGL sync failed 0x%x; synchronous fallback\\n",
                static_cast<unsigned>(eglGetError()));
            s.asyncSupported = false;
            asynchronous = false;
        }
    }
    if (!asynchronous) {
        glFinish();
        ++s.syncFrames;
    }
    {
        std::lock_guard lock(s.leaseMutex);
        slot.leased = frame;
        s.publishing = frame;
    }
    if ((s.asyncFrames + s.syncFrames) % 300 == 0) {
        std::fprintf(stderr, "ANGLE scanout mode: async=%llu sync=%llu busy=%llu\\n",
            static_cast<unsigned long long>(s.asyncFrames),
            static_cast<unsigned long long>(s.syncFrames),
            static_cast<unsigned long long>(s.busyFrames));
    }""")
text = replace(text, "    s.next = (s.next + 1) % kRingSize;", "    s.next = (selected + 1) % kRingSize;")
# The optional dump is another GPU reader and needs the same producer wait.
text = replace(text, "        id<MTLBlitCommandEncoder> blit = [commands blitCommandEncoder];", """        if (s.publishing && s.publishing->ready != nil)
            [commands encodeWaitForEvent:s.publishing->ready value:s.publishing->value];
        id<MTLBlitCommandEncoder> blit = [commands blitCommandEncoder];""")
text = replace(text, "} // namespace uml::gpu", """
AngleFrameLease angleScanoutLease(void* texture) noexcept
{
    auto& s = state();
    std::lock_guard lock(s.leaseMutex);
    if (s.publishing && (__bridge void*)s.publishing->texture == texture)
        return s.publishing;
    for (const auto& slot : s.ring) {
        if ((__bridge void*)slot.metal == texture)
            return slot.leased.lock();
    }
    return {};
}

void angleScanoutEncodeWait(void* commands, const AngleFrameLease& lease) noexcept
{
    if (!lease || commands == nullptr)
        return;
    const auto frame = std::static_pointer_cast<Frame>(lease);
    if (frame->ready != nil)
        [(__bridge id<MTLCommandBuffer>)commands encodeWaitForEvent:frame->ready value:frame->value];
}
} // namespace uml::gpu""")
path.write_text(text)

path = gpu / "metal_presentation.mm"
text = path.read_text()
text = replace(text, '#include "metal_presentation.hpp"', '#include "metal_presentation.hpp"\n#include "angle_scanout.hpp"')
text = replace(text, "    id<MTLTexture> latestTexture;", "    id<MTLTexture> latestTexture;\n    AngleFrameLease latestAngleLease;")
text = replace(text, "                latestTexture = texture;", """                latestTexture = texture;
                latestAngleLease = angleScanoutLease(scanout.texture);""")
# Clear ownership for reset/resize/CPU frames, not just the raw texture.
text = text.replace("latestTexture = nil;", "latestTexture = nil;\n                    latestAngleLease.reset();")
text = replace(text, "            id<MTLTexture> sourceTexture;", "            id<MTLTexture> sourceTexture;\n            AngleFrameLease sourceLease;")
text = replace(text, "                    sourceTexture = useCpu ? nil : latestTexture;", """                    sourceTexture = useCpu ? nil : latestTexture;
                    sourceLease = useCpu ? AngleFrameLease {} : latestAngleLease;""")
text = replace(text, "                pass.colorAttachments[0].loadAction = MTLLoadActionClear;\n                pass.colorAttachments[0].clearColor = clearColor;",
"""                angleScanoutEncodeWait((__bridge void*)buffer, sourceLease);
                pass.colorAttachments[0].loadAction = MTLLoadActionClear;
                pass.colorAttachments[0].clearColor = clearColor;""")
text = replace(text, """                    state->presentedFrames.fetch_add(
                        1, std::memory_order_relaxed);""", """                    state->presentedFrames.fetch_add(
                        1, std::memory_order_relaxed);
                    // The block owns the lease through GPU completion.
                    (void)sourceLease;""")
# Frame taps (screenshots/recording) are independent asynchronous readers.
text = replace(text, "                id<MTLTexture> source;", "                id<MTLTexture> source;\n                AngleFrameLease tapLease;")
text = replace(text, "                        source = latestTexture;", "                        source = latestTexture;\n                        tapLease = latestAngleLease;")
text = replace(text, "                id<MTLRenderCommandEncoder> encoder = buffer == nil ? nil :", """                angleScanoutEncodeWait((__bridge void*)buffer, tapLease);
                id<MTLRenderCommandEncoder> encoder = buffer == nil ? nil :""")
text = replace(text, "                [buffer addCompletedHandler:^(id<MTLCommandBuffer> finished) {", """                [buffer addCompletedHandler:^(id<MTLCommandBuffer> finished) {
                    (void)tapLease;""")
path.write_text(text)
print("async scanout: GPU event dependency and bounded leased triple-buffer installed")
