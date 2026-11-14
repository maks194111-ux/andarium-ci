// SPDX-License-Identifier: MIT
// Ask ANGLE's Metal backend (no Metal 4, no Vulkan) what OpenGL ES it offers.
// Uses the ANGLE build Apple ships inside WebKit (probe only, never linked into the app); declares the few entry points itself, so it needs no headers.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <string>

using EGLDisplay = void*; using EGLConfig = void*; using EGLContext = void*;
using EGLint = int; using EGLAttrib = intptr_t;

static void fail(const char* what) { std::fprintf(stderr, "FAIL: %s\n", what); std::exit(1); }
template <class T> static T sym(void* lib, const char* name) {
    void* p = dlsym(lib, name);
    if (!p) {  // some ANGLE builds export EGL_Foo / GL_Foo instead of eglFoo / glFoo
        std::string alternate = name[0] == 'e' ? "EGL_" + std::string(name + 3) : "GL_" + std::string(name + 2);
        p = dlsym(lib, alternate.c_str());
    }
    if (!p) fail(name);
    return reinterpret_cast<T>(p);
}

int main(int argc, char** argv) {
    setvbuf(stdout, nullptr, _IONBF, 0);
    void* gles = nullptr;
    for (int i = 1; i < argc && !gles; ++i) {
        gles = dlopen(argv[i], RTLD_NOW | RTLD_GLOBAL);
        std::printf("%s: %s\n", argv[i], gles ? "loaded" : "absent");
    }
    if (!gles) fail("no candidate ANGLE library could be loaded");
    void* egl = gles;

    auto getPlatformDisplay = sym<EGLDisplay (*)(unsigned, void*, const EGLAttrib*)>(egl, "eglGetPlatformDisplay");
    auto initialize = sym<unsigned (*)(EGLDisplay, EGLint*, EGLint*)>(egl, "eglInitialize");
    auto chooseConfig = sym<unsigned (*)(EGLDisplay, const EGLint*, EGLConfig*, EGLint, EGLint*)>(egl, "eglChooseConfig");
    auto createContext = sym<EGLContext (*)(EGLDisplay, EGLConfig, EGLContext, const EGLint*)>(egl, "eglCreateContext");
    auto makeCurrent = sym<unsigned (*)(EGLDisplay, void*, void*, EGLContext)>(egl, "eglMakeCurrent");
    auto queryString = sym<const char* (*)(EGLDisplay, EGLint)>(egl, "eglQueryString");
    auto getString = sym<const unsigned char* (*)(unsigned)>(gles, "glGetString");
    auto clearColor = sym<void (*)(float, float, float, float)>(gles, "glClearColor");
    auto clear = sym<void (*)(unsigned)>(gles, "glClear");
    auto readPixels = sym<void (*)(int, int, int, int, unsigned, unsigned, void*)>(gles, "glReadPixels");
    auto getError = sym<unsigned (*)()>(gles, "glGetError");
    auto getIntegerv = sym<void (*)(unsigned, int*)>(gles, "glGetIntegerv");

    // EGL_PLATFORM_ANGLE_ANGLE, EGL_PLATFORM_ANGLE_TYPE_ANGLE = EGL_PLATFORM_ANGLE_TYPE_METAL_ANGLE
    const EGLAttrib displayAttributes[] = {0x3203, 0x3489, 0x3038};
    EGLDisplay display = getPlatformDisplay(0x3202, nullptr, displayAttributes);
    if (!display) fail("ANGLE Metal display");
    EGLint major{}, minor{};
    if (!initialize(display, &major, &minor)) fail("initialize ANGLE on Metal");
    std::printf("EGL %d.%d\nEGL extensions: %s\n", major, minor, queryString(display, 0x3055));

    // ES3 renderable, RGBA8
    const EGLint configAttributes[] = {0x3040, 0x0040,
        0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8, 0x3038};
    EGLConfig config{}; EGLint count{};
    if (!chooseConfig(display, configAttributes, &config, 1, &count) || count != 1) fail("choose ES3 config");
    EGLContext context = nullptr;
    const int versions[][2] = {{3, 2}, {3, 1}, {3, 0}};
    for (const auto& v : versions) {
        const EGLint contextAttributes[] = {0x3098, v[0], 0x30FB, v[1], 0x3038};
        context = createContext(display, config, nullptr, contextAttributes);
        if (context) { std::printf("Highest OpenGL ES context: %d.%d\n", v[0], v[1]); break; }
    }
    if (!context) fail("create OpenGL ES 3.x context");
    // Surfaceless, as WebKit drives this backend; the frame goes to a renderbuffer.
    std::puts("stage: make current");
    if (!makeCurrent(display, nullptr, nullptr, context)) fail("make current without a surface");
    std::puts("stage: framebuffer");
    unsigned framebuffer{}, renderbuffer{};
    sym<void (*)(int, unsigned*)>(gles, "glGenFramebuffers")(1, &framebuffer);
    sym<void (*)(unsigned, unsigned)>(gles, "glBindFramebuffer")(0x8D40, framebuffer);
    sym<void (*)(int, unsigned*)>(gles, "glGenRenderbuffers")(1, &renderbuffer);
    sym<void (*)(unsigned, unsigned)>(gles, "glBindRenderbuffer")(0x8D41, renderbuffer);
    sym<void (*)(unsigned, unsigned, int, int)>(gles, "glRenderbufferStorage")(0x8D41, 0x8058, 16, 16);
    sym<void (*)(unsigned, unsigned, unsigned, unsigned)>(gles, "glFramebufferRenderbuffer")(0x8D40, 0x8CE0, 0x8D41, renderbuffer);
    if (sym<unsigned (*)(unsigned)>(gles, "glCheckFramebufferStatus")(0x8D40) != 0x8CD5) fail("framebuffer incomplete");
    std::puts("stage: strings");

    const char* renderer = reinterpret_cast<const char*>(getString(0x1F01));
    const char* extensions = reinterpret_cast<const char*>(getString(0x1F03));
    std::printf("GL version: %s\nGL renderer: %s\nGLSL: %s\nGL extensions: %s\n",
                reinterpret_cast<const char*>(getString(0x1F02)), renderer,
                reinterpret_cast<const char*>(getString(0x8B8C)), extensions);
    if (!renderer || !std::strstr(renderer, "Metal")) fail("renderer is not ANGLE Metal");
    int value{};
    getIntegerv(0x0D33, &value); std::printf("MAX_TEXTURE_SIZE %d\n", value);
    getIntegerv(0x8C8B, &value); std::printf("MAX_TRANSFORM_FEEDBACK_SEPARATE_ATTRIBS %d\n", value);
    getIntegerv(0x8824, &value); std::printf("MAX_DRAW_BUFFERS %d\n", value);

    // What the Android bridge leans on today; reported, not required.
    const char* wanted[] = {"GL_EXT_buffer_storage", "GL_OES_EGL_image", "GL_EXT_texture_buffer",
        "GL_OES_texture_buffer", "GL_EXT_geometry_shader", "GL_OES_geometry_shader",
        "GL_EXT_tessellation_shader", "GL_EXT_blend_func_extended", "GL_EXT_clip_cull_distance",
        "GL_EXT_multisampled_render_to_texture", "GL_OES_sample_shading", "GL_EXT_copy_image",
        "GL_OES_copy_image", "GL_EXT_texture_storage", "GL_EXT_color_buffer_float",
        "GL_EXT_draw_buffers_indexed", "GL_OES_draw_buffers_indexed", "GL_KHR_debug",
        "GL_EXT_texture_compression_s3tc", "GL_KHR_texture_compression_astc_ldr",
        "GL_EXT_base_instance", "GL_ANGLE_base_vertex_base_instance", "GL_EXT_draw_elements_base_vertex",
        "GL_OES_draw_elements_base_vertex", "GL_EXT_shader_framebuffer_fetch", "GL_EXT_sRGB_write_control",
        "GL_EXT_texture_sRGB_decode", "GL_EXT_texture_border_clamp", "GL_OES_texture_border_clamp",
        "GL_EXT_texture_cube_map_array", "GL_OES_texture_storage_multisample_2d_array",
        "GL_EXT_separate_shader_objects", "GL_OES_shader_image_atomic", "GL_EXT_texture_view",
        "GL_OES_texture_view", "GL_EXT_multi_draw_indirect", "GL_EXT_polygon_offset_clamp",
        "GL_EXT_depth_clamp", "GL_EXT_clip_control", "GL_ANGLE_texture_multisample"};
    for (const char* name : wanted) {
        const size_t length = std::strlen(name);
        bool present = false;
        for (const char* at = extensions; (at = std::strstr(at, name)); at += length)
            if (at[length] == ' ' || at[length] == 0) { present = true; break; }
        std::printf("BRIDGE %-48s %s\n", name, present ? "yes" : "NO");
    }

    clearColor(0.25f, 0.5f, 0.75f, 1.0f);
    clear(0x4000);
    unsigned char pixel[4]{};
    readPixels(8, 8, 1, 1, 0x1908, 0x1401, pixel);
    if (getError() != 0) fail("clear and readback");
    const int expected[] = {64, 128, 191, 255};
    for (int i = 0; i < 4; ++i)
        if (std::abs(pixel[i] - expected[i]) > 1) fail("framebuffer pixel mismatch");
    std::puts("PASS: ANGLE on Metal rendered and read back a frame");
    std::puts("Capability report only; not a Virgl integration or Android boot test.");
}
