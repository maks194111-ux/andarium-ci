#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Point Andarium's host GL provider at ANGLE's Metal backend (OpenGL ES).

Experiment for iOS 18, where the Metal 4 driver upstream needs is absent.
The engine is compiled as upstream's "software renderer" product (Virgl only,
no guest Vulkan, scanouts read back) but the GL underneath is ANGLE on the
GPU. Every replacement must match exactly once, or the script fails.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
path = root / "darwin/device/gpu/host_gl_provider.cpp"
text = path.read_text()


def replace(old: str, new: str) -> None:
    global text
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one match for: {old[:70]!r}")
    text = text.replace(old, new)


def cut(start: str, end: str, new: str) -> None:
    global text
    if text.count(start) != 1 or text.count(end) < 1:
        raise SystemExit(f"cannot find block starting: {start[:70]!r}")
    first = text.index(start)
    last = text.index(end, first)
    text = text[:first] + new + text[last:]


replace("constexpr EGLenum kClientApi = EGL_OPENGL_API;",
        "constexpr EGLenum kClientApi = EGL_OPENGL_ES_API;")
replace("constexpr EGLint kRenderableType = EGL_OPENGL_BIT;",
        "constexpr EGLint kRenderableType = EGL_OPENGL_ES3_BIT;")
cut("#if UML_GPU_SOFTWARE_RENDERER\n// The iOS Simulator has no Metal 4 device",
    "void reportEglFailure(",
    '''// ANGLE's Metal backend: OpenGL ES on the GPU without Metal 4 or Vulkan.
constexpr const char* kProviderName = "ANGLE/Metal";
constexpr const char* kProviderMarker =
    "Virgl ANGLE/Metal provider: hardware, OpenGL ES\\n";
// EGL_ANGLE_platform_angle and EGL_ANGLE_platform_angle_metal.
constexpr EGLenum kAnglePlatform = 0x3202;
constexpr EGLAttrib kAnglePlatformType = 0x3203;
constexpr EGLAttrib kAnglePlatformTypeMetal = 0x3489;

''')
cut("bool hasExtension(const char* extensions, std::string_view name) noexcept",
    "std::string glString(GLenum name)", "")
cut("        // Mesa selects its Gallium driver from the process environment",
    "        if (eglDisplay == EGL_NO_DISPLAY) {",
    '''        const EGLAttrib displayAttributes[] {
            kAnglePlatformType, kAnglePlatformTypeMetal,
            EGL_NONE,
        };
        const auto eglDisplay = eglGetPlatformDisplay(
            kAnglePlatform, nullptr, displayAttributes);
''')
profile = '''            EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,
            EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,
'''
if text.count(profile) != 2:
    raise SystemExit("expected two core-profile requests")
# A profile mask is a bad attribute for an OpenGL ES context.
text = text.replace(profile, "")
replace('''            parameters.major_ver < 3 ||
            parameters.major_ver > 4) {''',
        '''            parameters.major_ver != 3 || parameters.minor_ver != 0) {''')
replace("        // vrend probes desktop versions from 4.6 downwards and never asks for\n"
        "        // a compatibility profile on this provider.\n",
        "        // vrend probes versions from 4.6 downwards; ANGLE's Metal backend\n"
        "        // serves OpenGL ES 3.0, so every other request is refused here.\n")
path.write_text(text)

# Mesa exports a lookup from a GL texture to the Metal texture that stores it.
# ANGLE has no such export; answer "unsupported" so scanouts take the readback
# path, exactly as on upstream's software product.
(root / "darwin/device/gpu/angle_interop_unsupported.c").write_text('''// SPDX-License-Identifier: GPL-2.0-or-later
// ANGLE cannot name the Metal texture behind a GL object. virglrenderer asks
// through Mesa's interop entry point; report it unsupported so the display
// reads the scanout back instead.
int MesaGLInteropEGLExportObject(void *display, void *context, void *in, void *out);
int MesaGLInteropEGLExportObject(void *display, void *context, void *in, void *out)
{
   (void)display; (void)context; (void)in; (void)out;
   return 10; /* MESA_GLINTEROP_UNSUPPORTED */
}
''')
print("host GL provider now targets ANGLE/Metal")
