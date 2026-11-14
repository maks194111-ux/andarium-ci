// SPDX-License-Identifier: GPL-2.0-or-later
// Drive Andarium's own renderer classes (VirglRenderer over HostGlProvider),
// patched to use ANGLE on Metal, through one guest-style frame.
#include "virgl_renderer.hpp"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <span>
#include <vector>

extern "C" {
#include <virgl_hw.h>
#include <virgl_protocol.h>
}

using uml::gpu::VirglRenderer;

static std::uint32_t bits(float value)
{
    std::uint32_t result;
    std::memcpy(&result, &value, sizeof(result));
    return result;
}

static void require(int result, const char* what)
{
    if (result == 0)
        return;
    std::fprintf(stderr, "FAIL: %s returned %d\n", what, result);
    std::exit(1);
}

int main()
{
    setvbuf(stdout, nullptr, _IONBF, 0);
    VirglRenderer renderer;
    std::puts("engine renderer constructed");
    const auto capset = renderer.capset(2);
    std::printf("Virgl capset version %u, %zu bytes\n", capset.maximumVersion, capset.data.size());
    if (capset.data.size() >= sizeof(virgl_caps_v1)) {
        virgl_caps_v1 caps;
        std::memcpy(&caps, capset.data.data(), sizeof(caps));
        std::printf("guest GLSL level %u, render targets %u\n", caps.glsl_level, caps.max_render_targets);
    }
    try {
        std::printf("Venus (guest Vulkan) capset bytes: %zu\n", renderer.capset(4).data.size());
    } catch (const std::exception& error) {
        std::printf("Venus (guest Vulkan) capset: none (%s)\n", error.what());
    }

    const std::uint32_t context = 1, resource = 1, surface = 1;
    require(renderer.createContext(context, 0, "probe"), "context creation");
    require(renderer.createResource3d({
        .resourceId = resource, .target = 2, .format = VIRGL_FORMAT_B8G8R8A8_UNORM,
        .bind = VIRGL_BIND_RENDER_TARGET, .width = 64, .height = 64, .depth = 1, .arraySize = 1,
    }), "resource creation");
    require(renderer.attachResource(context, resource), "resource attach");

    std::vector<std::uint32_t> words {
        VIRGL_CMD0(VIRGL_CCMD_CREATE_OBJECT, VIRGL_OBJECT_SURFACE, VIRGL_OBJ_SURFACE_SIZE),
        surface, resource, VIRGL_FORMAT_B8G8R8A8_UNORM, 0, 0,
        VIRGL_CMD0(VIRGL_CCMD_SET_FRAMEBUFFER_STATE, 0, VIRGL_SET_FRAMEBUFFER_STATE_SIZE(1)),
        1, 0, surface,
        VIRGL_CMD0(VIRGL_CCMD_CLEAR, 0, VIRGL_OBJ_CLEAR_SIZE),
        4, bits(0.25f), bits(0.5f), bits(0.75f), bits(1.0f), 0, 0, 0,
    };
    require(renderer.submit(context, {reinterpret_cast<const std::uint8_t*>(words.data()),
                                      words.size() * sizeof(std::uint32_t)}), "command stream");

    // The display's readback path: what a scanout takes when no Metal texture is named.
    VirglRenderer::NativeTexture texture;
    std::printf("Metal texture lookup: %d (non-zero means the display reads back)\n",
                renderer.resourceMetalTexture(resource, texture));
    std::vector<std::uint8_t> pixels(64 * 64 * 4);
    require(renderer.readResourceRectangle(resource, pixels, 0, 0, 64, 64), "scanout readback");
    const std::uint8_t* pixel = pixels.data() + (32 * 64 + 32) * 4;
    std::printf("BGRA pixel %u %u %u %u\n", pixel[0], pixel[1], pixel[2], pixel[3]);
    const int expected[] = {191, 128, 64, 255};
    for (int i = 0; i < 4; ++i) {
        if (std::abs(pixel[i] - expected[i]) > 1) {
            std::fputs("FAIL: pixel mismatch\n", stderr);
            return 1;
        }
    }
    renderer.destroyContext(context);
    std::puts("PASS: Andarium's renderer drew and read back a frame on ANGLE/Metal");
    std::puts("macOS host test; no Android guest and no iPhone.");
    return 0;
}
