#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Show guest frames without reading them back to the CPU (ANGLE path).

Upstream's Virgl-only mode reads every guest frame back into memory and
uploads it again for display.  On ANGLE there is no call that names the Metal
texture behind a GL texture, so this patch keeps three Metal textures of its
own, wraps each as a GL texture (EGL_ANGLE_metal_texture_client_buffer), and
copies the guest's frame into the next one on the GPU.  The display then
samples that Metal texture through upstream's existing direct path.  When
anything is missing the answer is "no texture" and the frame takes the
readback path as before.
Run after angle_provider.py and engine_build_patch.py.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
gpu = root / "darwin/device/gpu"


def edit(name: str, changes) -> None:
    path = gpu / name
    text = path.read_text()
    for old, new, count in changes:
        if text.count(old) != count:
            raise SystemExit(f"{name}: expected {count} of {old[:60]!r}, found {text.count(old)}")
        text = text.replace(old, new)
    path.write_text(text)


(gpu / "angle_scanout.hpp").write_text('''// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <cstdint>

namespace uml::gpu {

/* Copies a GL texture into one of this module's Metal textures on the GPU and
 * returns that Metal texture, borrowed, or nullptr when the copy cannot be
 * made. Called on the thread that owns the renderer's GL contexts, with one
 * of them current. The returned texture keeps its contents until the third
 * following call. */
[[nodiscard]] void* angleScanoutCopy(
    void* eglDisplay,
    std::uint32_t glTexture,
    std::uint32_t width,
    std::uint32_t height) noexcept;

} // namespace uml::gpu
''')

(gpu / "angle_scanout.mm").write_text(r'''// SPDX-License-Identifier: GPL-2.0-or-later
// Experiment: GPU-side copy of a guest scanout into a Metal texture the
// display can sample, for a host GL (ANGLE) that cannot name the Metal
// texture behind a GL object.

#include "angle_scanout.hpp"

#import <Metal/Metal.h>

#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unistd.h>
#include <vector>
#include <epoxy/egl.h>
#include <epoxy/gl.h>

namespace uml::gpu {
namespace {

// EGL_ANGLE_metal_texture_client_buffer.
constexpr EGLenum kMetalTextureAngle = 0x34A7;
constexpr std::size_t kRingSize = 3;

struct Slot {
    id<MTLTexture> metal;
    EGLImageKHR image {EGL_NO_IMAGE_KHR};
    GLuint texture {};
};

struct State {
    bool probed {};
    bool usable {};
    bool reported {};
    id<MTLDevice> device;
    EGLDisplay display {EGL_NO_DISPLAY};
    std::uint32_t width {};
    std::uint32_t height {};
    std::array<Slot, kRingSize> ring;
    std::size_t next {};
    std::uint64_t frames {};
};

State& state() noexcept
{
    static State instance;
    return instance;
}

void releaseRing(State& s) noexcept
{
    for (auto& slot : s.ring) {
        if (slot.texture != 0)
            glDeleteTextures(1, &slot.texture);
        if (slot.image != EGL_NO_IMAGE_KHR)
            eglDestroyImageKHR(s.display, slot.image);
        slot = {};
    }
    s.width = 0;
    s.height = 0;
}

bool buildRing(State& s, std::uint32_t width, std::uint32_t height) noexcept
{
    releaseRing(s);
    GLint boundTexture = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &boundTexture);
    bool complete = true;
    @autoreleasepool {
        MTLTextureDescriptor* descriptor = [MTLTextureDescriptor
            texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                                         width:width
                                        height:height
                                     mipmapped:NO];
        descriptor.usage =
            MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        descriptor.storageMode = MTLStorageModePrivate;
        for (auto& slot : s.ring) {
            slot.metal = [s.device newTextureWithDescriptor:descriptor];
            if (slot.metal == nil) {
                complete = false;
                break;
            }
            const EGLint attributes[] {EGL_NONE};
            slot.image = eglCreateImageKHR(
                s.display,
                EGL_NO_CONTEXT,
                kMetalTextureAngle,
                (__bridge EGLClientBuffer)slot.metal,
                attributes);
            if (slot.image == EGL_NO_IMAGE_KHR) {
                std::fprintf(
                    stderr,
                    "ANGLE scanout: Metal texture image refused (EGL 0x%x)\n",
                    static_cast<unsigned>(eglGetError()));
                complete = false;
                break;
            }
            glGenTextures(1, &slot.texture);
            glBindTexture(GL_TEXTURE_2D, slot.texture);
            glEGLImageTargetTexture2DOES(GL_TEXTURE_2D, slot.image);
            if (glGetError() != GL_NO_ERROR) {
                std::fputs("ANGLE scanout: image texture refused\n", stderr);
                complete = false;
                break;
            }
        }
    }
    glBindTexture(GL_TEXTURE_2D, static_cast<GLuint>(boundTexture));
    if (!complete) {
        releaseRing(s);
        return false;
    }
    s.width = width;
    s.height = height;
    s.next = 0;
    return true;
}

// A measurement aid, off unless UML_ANGLE_SCANOUT_DUMP names a file: when
// "<file>.request" exists, the copy just made is read back and written there
// as raw BGRA rows, bottom row first, after a "width height" text line.
void maybeDump(std::uint32_t width, std::uint32_t height) noexcept
{
    static const char* path = std::getenv("UML_ANGLE_SCANOUT_DUMP");
    if (path == nullptr)
        return;
    const std::string request = std::string(path) + ".request";
    if (access(request.c_str(), F_OK) != 0)
        return;
    std::vector<unsigned char> pixels(
        static_cast<std::size_t>(width) * height * 4U);
    glReadPixels(
        0, 0, static_cast<GLsizei>(width), static_cast<GLsizei>(height),
        GL_BGRA_EXT, GL_UNSIGNED_BYTE, pixels.data());
    const bool read = glGetError() == GL_NO_ERROR;
    if (FILE* out = read ? std::fopen(path, "wb") : nullptr) {
        std::fprintf(out, "%u %u\n", width, height);
        std::fwrite(pixels.data(), 1, pixels.size(), out);
        std::fclose(out);
    }
    unlink(request.c_str());
}

} // namespace

void* angleScanoutCopy(
    void* eglDisplay,
    std::uint32_t glTexture,
    std::uint32_t width,
    std::uint32_t height) noexcept
{
    auto& s = state();
    if (eglDisplay == nullptr || glTexture == 0 || width == 0 || height == 0 ||
        eglGetCurrentContext() == EGL_NO_CONTEXT) {
        return nullptr;
    }
    if (!s.probed) {
        s.probed = true;
        s.display = static_cast<EGLDisplay>(eglDisplay);
        const char* extensions = eglQueryString(s.display, EGL_EXTENSIONS);
        const bool offered = extensions != nullptr &&
            std::strstr(extensions, "EGL_ANGLE_metal_texture_client_buffer") != nullptr;
        const bool disabled = std::getenv("UML_ANGLE_SCANOUT_READBACK") != nullptr;
        s.device = MTLCreateSystemDefaultDevice();
        s.usable = offered && !disabled && s.device != nil;
        std::fprintf(
            stderr,
            "ANGLE scanout: GPU copy %s (extension %s)\n",
            s.usable ? "on" : "off",
            offered ? "offered" : "absent");
    }
    if (!s.usable)
        return nullptr;
    if ((s.width != width || s.height != height) &&
        !buildRing(s, width, height)) {
        s.usable = false;
        std::fputs("ANGLE scanout: GPU copy off, frames are read back\n", stderr);
        return nullptr;
    }

    // The renderer caches the GL state of its contexts; leave every binding
    // this copy touches as it was.
    GLint readFramebuffer = 0;
    GLint drawFramebuffer = 0;
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &readFramebuffer);
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &drawFramebuffer);
    const GLboolean scissor = glIsEnabled(GL_SCISSOR_TEST);
    while (glGetError() != GL_NO_ERROR) {
    }

    auto& slot = s.ring[s.next];
    GLuint framebuffers[2] {};
    glGenFramebuffers(2, framebuffers);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, framebuffers[0]);
    glFramebufferTexture2D(
        GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, glTexture, 0);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, framebuffers[1]);
    glFramebufferTexture2D(
        GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, slot.texture, 0);
    bool copied =
        glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE &&
        glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    if (copied) {
        if (scissor)
            glDisable(GL_SCISSOR_TEST);
        glBlitFramebuffer(
            0, 0, static_cast<GLint>(width), static_cast<GLint>(height),
            0, 0, static_cast<GLint>(width), static_cast<GLint>(height),
            GL_COLOR_BUFFER_BIT, GL_NEAREST);
        copied = glGetError() == GL_NO_ERROR;
        if (copied) {
            glBindFramebuffer(GL_READ_FRAMEBUFFER, framebuffers[1]);
            maybeDump(width, height);
        }
        if (scissor)
            glEnable(GL_SCISSOR_TEST);
    }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(readFramebuffer));
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, static_cast<GLuint>(drawFramebuffer));
    glDeleteFramebuffers(2, framebuffers);
    if (!copied) {
        while (glGetError() != GL_NO_ERROR) {
        }
        if (!s.reported) {
            s.reported = true;
            std::fputs("ANGLE scanout: a frame could not be copied on the GPU\n", stderr);
        }
        return nullptr;
    }
    // The display samples the texture from its own Metal queue; the copy has
    // to be complete before that, and Metal orders nothing across queues.
    glFinish();
    s.next = (s.next + 1) % kRingSize;
    if (++s.frames == 1)
        std::fputs("ANGLE scanout: first frame copied on the GPU\n", stderr);
    return (__bridge void*)slot.metal;
}

} // namespace uml::gpu
''')

edit("CMakeLists.txt", [
    ("    angle_interop_unsupported.c\n    host_gl_provider.cpp\n",
     "    angle_interop_unsupported.c\n    angle_scanout.mm\n    host_gl_provider.cpp\n", 1),
])
edit("virgl_renderer.cpp", [
    ('#include "virgl_renderer.hpp"\n\n',
     '#include "virgl_renderer.hpp"\n\n#include "angle_scanout.hpp"\n', 1),
    ("""    if (information.native_type != VIRGL_NATIVE_HANDLE_METAL_TEXTURE ||
        information.native_handle == nullptr) {
        return EINVAL;
    }
    texture = NativeTexture {
        .texture = information.native_handle,
""",
     """    // ANGLE names no Metal texture for a GL object: copy the frame on the
    // GPU into a Metal texture of this process and show that one.
    void* const nativeHandle = angleScanoutCopy(
        provider_->display(),
        information.base.tex_id,
        information.base.width,
        information.base.height);
    if (nativeHandle == nullptr)
        return EINVAL;
    texture = NativeTexture {
        .texture = nativeHandle,
""", 1),
])
# The device's direct-presentation branches and their helper are compiled out
# in the Virgl-only mode; this path needs them.
edit("virtio_gpu_device.cpp", [
    ("#if !UML_GPU_SOFTWARE_RENDERER\n/* Two formats that differ only",
     "#if 1 // ANGLE scanout copy\n/* Two formats that differ only", 1),
    ("#if !UML_GPU_SOFTWARE_RENDERER\n            VirglRenderer::NativeTexture nativeTexture;",
     "#if 1 // ANGLE scanout copy\n            VirglRenderer::NativeTexture nativeTexture;", 1),
    ("#if !UML_GPU_SOFTWARE_RENDERER\n                VirglRenderer::NativeTexture nativeTexture;",
     "#if 1 // ANGLE scanout copy\n                VirglRenderer::NativeTexture nativeTexture;", 1),
])
print("scanout: guest frames are copied on the GPU, readback is the fallback")
