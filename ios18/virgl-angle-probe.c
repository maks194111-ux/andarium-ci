// SPDX-License-Identifier: MIT
// Drive Andarium's patched virglrenderer the way the engine does (its own EGL
// contexts through callbacks), but on ANGLE's Metal backend. Then render one
// frame through the Virgl command stream and read it back.
#include <epoxy/egl.h>
#include <epoxy/gl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/uio.h>
#include "virglrenderer.h"
#include "virgl_hw.h"
#include "virgl_protocol.h"

static EGLDisplay display;
static EGLConfig config;

static void fail(const char *what)
{
   fprintf(stderr, "FAIL: %s (EGL error 0x%x)\n", what, eglGetError());
   exit(1);
}

static virgl_renderer_gl_context create_context(void *cookie, int scanout, struct virgl_renderer_gl_ctx_param *param)
{
   (void)cookie; (void)scanout;
   const EGLint attributes[] = {EGL_CONTEXT_MAJOR_VERSION, param->major_ver,
                                EGL_CONTEXT_MINOR_VERSION, param->minor_ver, EGL_NONE};
   EGLContext context = eglCreateContext(display, config, param->shared ? eglGetCurrentContext() : EGL_NO_CONTEXT, attributes);
   printf("context request %d.%d shared=%d: %s\n", param->major_ver, param->minor_ver,
          param->shared, context != EGL_NO_CONTEXT ? "created" : "refused");
   if (context == EGL_NO_CONTEXT)
      printf("  EGL error 0x%x\n", eglGetError());
   return context == EGL_NO_CONTEXT ? NULL : (virgl_renderer_gl_context)context;
}

static void destroy_context(void *cookie, virgl_renderer_gl_context context)
{
   (void)cookie;
   eglDestroyContext(display, (EGLContext)context);
}

static int make_current(void *cookie, int scanout, virgl_renderer_gl_context context)
{
   (void)cookie; (void)scanout;
   return eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, (EGLContext)context) ? 0 : -1;
}

static void write_fence(void *cookie, uint32_t fence) { (void)cookie; (void)fence; }
static void write_context_fence(void *cookie, uint32_t context, uint32_t ring, uint64_t fence)
{
   (void)cookie; (void)context; (void)ring; (void)fence;
}
static void *get_egl_display(void *cookie) { (void)cookie; return display; }

// Mesa's interop export, which ANGLE does not have: report it unsupported.
int MesaGLInteropEGLExportObject(void *d, void *c, void *in, void *out);
int MesaGLInteropEGLExportObject(void *d, void *c, void *in, void *out)
{
   (void)d; (void)c; (void)in; (void)out;
   return 10; /* MESA_GLINTEROP_UNSUPPORTED */
}

static uint32_t float_bits(float value) { uint32_t bits; memcpy(&bits, &value, 4); return bits; }

int main(void)
{
   setvbuf(stdout, NULL, _IONBF, 0);
   // libepoxy can only resolve EGL 1.0 entry points before a display exists.
   // This ANGLE build has Metal as its only backend, so the default display is Metal.
   display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
   if (display == EGL_NO_DISPLAY) fail("ANGLE Metal display");
   EGLint major, minor;
   if (!eglInitialize(display, &major, &minor)) fail("initialize ANGLE");
   if (!eglBindAPI(EGL_OPENGL_ES_API)) fail("bind OpenGL ES");
   const EGLint config_attributes[] = {EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
      EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
   EGLint count;
   if (!eglChooseConfig(display, config_attributes, &config, 1, &count) || count != 1) fail("choose config");

   static struct virgl_renderer_callbacks callbacks = {
      .version = VIRGL_RENDERER_CALLBACKS_VERSION,
      .write_fence = write_fence,
      .create_gl_context = create_context,
      .destroy_gl_context = destroy_context,
      .make_current = make_current,
      .write_context_fence = write_context_fence,
      .get_egl_display = get_egl_display,
   };
   int result = virgl_renderer_init(&callbacks, 0, &callbacks);
   if (result) { fprintf(stderr, "FAIL: virgl_renderer_init returned %d\n", result); return 1; }
   printf("virglrenderer initialised on: %s / %s\n", (const char *)glGetString(GL_VERSION),
          (const char *)glGetString(GL_RENDERER));

   uint32_t version = 0, size = 0;
   virgl_renderer_get_cap_set(2 /* VIRGL2 capset */, &version, &size);
   if (!size) { fprintf(stderr, "FAIL: no Virgl capability set\n"); return 1; }
   union virgl_caps *caps = calloc(1, size > sizeof(*caps) ? size : sizeof(*caps));
   virgl_renderer_fill_caps(2 /* VIRGL2 capset */, version, caps);
   printf("capset version %u size %u\n", version, size);
   printf("guest GLSL level %u, render targets %u, max samples %u\n",
          caps->v1.glsl_level, caps->v1.max_render_targets, caps->v1.max_samples);
   printf("max texture 2D %u, UBOs %u, dual-source targets %u, capability bits 0x%x / v2 0x%x\n",
          caps->v2.max_texture_2d_size, caps->v1.max_uniform_blocks,
          caps->v1.max_dual_source_render_targets, caps->v2.capability_bits, caps->v2.capability_bits_v2);

   const uint32_t context = 1, resource = 1, surface = 1;
   result = virgl_renderer_context_create(context, 5, "probe");
   if (result) { fprintf(stderr, "FAIL: context create returned %d\n", result); return 1; }
   struct virgl_renderer_resource_create_args args = {
      .handle = resource, .target = 2 /* PIPE_TEXTURE_2D */, .format = VIRGL_FORMAT_R8G8B8A8_UNORM,
      .bind = VIRGL_BIND_RENDER_TARGET, .width = 16, .height = 16, .depth = 1, .array_size = 1,
   };
   result = virgl_renderer_resource_create(&args, NULL, 0);
   if (result) { fprintf(stderr, "FAIL: resource create returned %d\n", result); return 1; }
   virgl_renderer_ctx_attach_resource(context, resource);

   uint32_t commands[32];
   unsigned n = 0;
   commands[n++] = VIRGL_CMD0(VIRGL_CCMD_CREATE_OBJECT, VIRGL_OBJECT_SURFACE, VIRGL_OBJ_SURFACE_SIZE);
   commands[n++] = surface;
   commands[n++] = resource;
   commands[n++] = VIRGL_FORMAT_R8G8B8A8_UNORM;
   commands[n++] = 0; /* level */
   commands[n++] = 0; /* first and last layer */
   commands[n++] = VIRGL_CMD0(VIRGL_CCMD_SET_FRAMEBUFFER_STATE, 0, VIRGL_SET_FRAMEBUFFER_STATE_SIZE(1));
   commands[n++] = 1;
   commands[n++] = 0; /* no depth */
   commands[n++] = surface;
   commands[n++] = VIRGL_CMD0(VIRGL_CCMD_CLEAR, 0, VIRGL_OBJ_CLEAR_SIZE);
   commands[n++] = 4; /* PIPE_CLEAR_COLOR0 */
   commands[n++] = float_bits(0.25f);
   commands[n++] = float_bits(0.5f);
   commands[n++] = float_bits(0.75f);
   commands[n++] = float_bits(1.0f);
   commands[n++] = 0; commands[n++] = 0; /* depth */
   commands[n++] = 0; /* stencil */
   result = virgl_renderer_submit_cmd(commands, context, n);
   if (result) { fprintf(stderr, "FAIL: command stream returned %d\n", result); return 1; }

   static unsigned char pixels[16 * 16 * 4];
   struct iovec iov = {.iov_base = pixels, .iov_len = sizeof(pixels)};
   struct virgl_box box = {.w = 16, .h = 16, .d = 1};
   result = virgl_renderer_transfer_read_iov(resource, context, 0, 0, 0, &box, 0, &iov, 1);
   if (result) { fprintf(stderr, "FAIL: readback returned %d\n", result); return 1; }
   const unsigned char *pixel = pixels + (8 * 16 + 8) * 4;
   printf("pixel %u %u %u %u\n", pixel[0], pixel[1], pixel[2], pixel[3]);
   const int expected[] = {64, 128, 191, 255};
   for (int i = 0; i < 4; i++)
      if (abs(pixel[i] - expected[i]) > 1) { fprintf(stderr, "FAIL: pixel mismatch\n"); return 1; }

   virgl_renderer_context_destroy(context);
   virgl_renderer_cleanup(&callbacks);
   puts("PASS: Virgl command stream rendered through ANGLE on Metal and read back");
   puts("Host-side test only; no Android guest, no iPhone.");
   return 0;
}
