// SPDX-License-Identifier: GPL-2.0-or-later
// Real ANGLE producer -> independent Metal queue, not a mocked fence test.
#include "angle_scanout.hpp"
#include <epoxy/egl.h>
#include <epoxy/gl.h>
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>

using namespace uml::gpu;

struct Snapshot {
    id<MTLTexture> texture;
    AngleFrameLease lease;
    unsigned char red;
};

int main()
{
    @autoreleasepool {
        auto display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
        assert(eglInitialize(display, nullptr, nullptr));
        assert(eglBindAPI(EGL_OPENGL_ES_API));
        const EGLint configAttributes[] {
            EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
            EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
        EGLConfig config;
        EGLint count;
        assert(eglChooseConfig(display, configAttributes, &config, 1, &count) && count == 1);
        const EGLint contextAttributes[] {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
        auto context = eglCreateContext(display, config, EGL_NO_CONTEXT, contextAttributes);
        assert(context != EGL_NO_CONTEXT);
        const EGLint surfaceAttributes[] {EGL_WIDTH, 64, EGL_HEIGHT, 64, EGL_NONE};
        auto surface = eglCreatePbufferSurface(display, config, surfaceAttributes);
        assert(eglMakeCurrent(display, surface, surface, context));
        assert(std::strstr(eglQueryString(display, EGL_EXTENSIONS),
                          "EGL_ANGLE_metal_shared_event_sync") != nullptr);
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        id<MTLCommandQueue> consumer = [device newCommandQueue];
        GLuint texture, framebuffer;
        glGenTextures(1, &texture);
        glBindTexture(GL_TEXTURE_2D, texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 64, 64, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glGenFramebuffers(1, &framebuffer);
        glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
        assert(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE);

        auto produce = [&](unsigned char red) {
            glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
            glClearColor(red / 255.0f, 0.25f, 0.75f, 1.0f);
            glClear(GL_COLOR_BUFFER_BIT);
            void* handle = angleScanoutCopy(display, texture, 64, 64);
            return Snapshot {(__bridge id<MTLTexture>)handle, angleScanoutLease(handle), red};
        };
        auto verify = [&](const Snapshot& snapshot) {
            assert(snapshot.texture != nil && snapshot.lease);
            id<MTLBuffer> pixels = [device newBufferWithLength:64*64*4 options:MTLResourceStorageModeShared];
            id<MTLCommandBuffer> command = [consumer commandBuffer];
            angleScanoutEncodeWait((__bridge void*)command, snapshot.lease);
            id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
            [blit copyFromTexture:snapshot.texture sourceSlice:0 sourceLevel:0
                    sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(64, 64, 1)
                    toBuffer:pixels destinationOffset:0 destinationBytesPerRow:256
                    destinationBytesPerImage:64*256];
            [blit endEncoding];
            [command commit];
            [command waitUntilCompleted]; // test oracle only, not the producer
            assert(command.status == MTLCommandBufferStatusCompleted);
            auto* bytes = static_cast<const unsigned char*>(pixels.contents);
            for (int i = 0; i < 64*64; ++i) {
                assert(std::abs(int(bytes[i*4]) - 191) <= 1);
                assert(std::abs(int(bytes[i*4+1]) - 64) <= 1);
                assert(std::abs(int(bytes[i*4+2]) - snapshot.red) <= 1);
                assert(bytes[i*4+3] == 255);
            }
        };
        for (const char* mode : {"0", "1"}) {
            setenv("UML_ANGLE_ASYNC", mode, 1);
            for (int cycle = 0; cycle < 100; ++cycle) {
                std::array<Snapshot, 3> held {produce(17), produce(99), produce(237)};
                for (auto& frame : held)
                    assert(frame.texture != nil && frame.lease);
                // All consumers delayed: do not overwrite or grow the ring.
                assert(produce(42).texture == nil);
                // Read the oldest AFTER the producer tried to wrap around.
                for (auto& frame : held)
                    verify(frame);
                held[0] = {};
                auto reused = produce(53);
                verify(reused);
                verify(held[1]);
                verify(held[2]);
            }
            std::printf("PASS: mode=%s, 100 ring wraps, all pixels, delayed consumers and saturation\n", mode);
        }
        // Resize must retain old textures until their readers finish.
        auto old = produce(123);
        glBindTexture(GL_TEXTURE_2D, texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 32, 32, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glClear(GL_COLOR_BUFFER_BIT);
        assert(angleScanoutCopy(display, texture, 32, 32) != nullptr);
        verify(old);
        std::puts("PASS: resize retains the outstanding old-size frame");
    }
}
