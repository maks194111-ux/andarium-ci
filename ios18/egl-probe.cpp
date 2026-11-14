// SPDX-License-Identifier: MIT
// Exercise the actual Zink OpenGL provider, not just the underlying Vulkan ICD.
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

static void require(bool ok, const char* operation) {
    if (!ok) {
        std::fprintf(stderr, "FAIL: %s (EGL error 0x%x)\n", operation, eglGetError());
        std::exit(1);
    }
}

template <class T> static T proc(const char* name) {
    auto pointer = eglGetProcAddress(name);
    require(pointer != nullptr, name);
    return reinterpret_cast<T>(pointer);
}

int main() {
    EGLDisplay display = eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA,
                                               EGL_DEFAULT_DISPLAY, nullptr);
    require(display != EGL_NO_DISPLAY, "surfaceless display");
    EGLint major{}, minor{};
    require(eglInitialize(display, &major, &minor), "initialize Zink EGL");
    std::printf("EGL %d.%d\n", major, minor);
    require(eglBindAPI(EGL_OPENGL_API), "bind desktop OpenGL");
    const EGLint configAttributes[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE
    };
    EGLConfig config{};
    EGLint count{};
    require(eglChooseConfig(display, configAttributes, &config, 1, &count) && count == 1,
            "choose framebuffer format");
    // Match the existing host provider contract. Do not silently request a
    // lower GL version, software rasterizer, or override reported features.
    const EGLint contextAttributes[] = {
        EGL_CONTEXT_MAJOR_VERSION, 4, EGL_CONTEXT_MINOR_VERSION, 6,
        EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE
    };
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, contextAttributes);
    require(context != EGL_NO_CONTEXT, "create required OpenGL 4.6 core context");
    const EGLint surfaceAttributes[] = {EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE};
    EGLSurface surface = eglCreatePbufferSurface(display, config, surfaceAttributes);
    require(surface != EGL_NO_SURFACE, "create offscreen surface");
    require(eglMakeCurrent(display, surface, surface, context), "make current");
    const auto getString = proc<PFNGLGETSTRINGPROC>("glGetString");
    const auto clearColor = proc<PFNGLCLEARCOLORPROC>("glClearColor");
    const auto clear = proc<PFNGLCLEARPROC>("glClear");
    const auto read = proc<PFNGLREADPIXELSPROC>("glReadPixels");
    const auto getError = proc<PFNGLGETERRORPROC>("glGetError");
    const char* renderer = reinterpret_cast<const char*>(getString(GL_RENDERER));
    std::printf("GL version: %s\n", reinterpret_cast<const char*>(getString(GL_VERSION)));
    std::printf("GL renderer: %s\n", renderer ? renderer : "(missing)");
    require(renderer && (std::strstr(renderer, "zink") || std::strstr(renderer, "Zink")),
            "Zink hardware route rather than software fallback");
    clearColor(0.25f, 0.5f, 0.75f, 1.0f);
    clear(GL_COLOR_BUFFER_BIT);
    unsigned char pixel[4]{};
    read(8, 8, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    require(getError() == GL_NO_ERROR, "OpenGL clear and readback");
    const int expected[] = {64, 128, 191, 255};
    for (int i = 0; i < 4; ++i)
        require(std::abs(static_cast<int>(pixel[i]) - expected[i]) <= 1,
                "framebuffer pixel matches submitted color");
    require(eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT), "unbind");
    require(eglDestroySurface(display, surface), "destroy surface");
    require(eglDestroyContext(display, context), "destroy context");
    require(eglTerminate(display), "terminate");
    std::puts("PASS: Zink/MoltenVK OpenGL 4.6 clear and framebuffer readback");
    std::puts("Not yet a Virgl/Venus integration or Android boot test.");
}
