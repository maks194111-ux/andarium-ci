// SPDX-License-Identifier: MIT
// Checks, inside the Android guest, the GL operations Skia's text path relies
// on: one-channel textures (R8, ALPHA, LUMINANCE) uploaded whole and in parts,
// unnormalized 16-bit vertex attributes, and coverage blending. Each line
// prints what was read back next to what a correct driver returns.
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <stdio.h>
#include <string.h>

static GLuint program(const char *vs, const char *fs)
{
    GLuint p = glCreateProgram();
    const char *src[2] = {vs, fs};
    GLenum kinds[2]    = {GL_VERTEX_SHADER, GL_FRAGMENT_SHADER};
    for (int i = 0; i < 2; ++i) {
        GLuint s = glCreateShader(kinds[i]);
        glShaderSource(s, 1, &src[i], NULL);
        glCompileShader(s);
        GLint ok = 0;
        glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
        if (!ok) {
            char log[1024];
            glGetShaderInfoLog(s, sizeof log, NULL, log);
            printf("compile failed: %s\n", log);
        }
        glAttachShader(p, s);
    }
    glBindAttribLocation(p, 0, "p");
    glBindAttribLocation(p, 1, "a");
    glLinkProgram(p);
    GLint ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) printf("link failed\n");
    glUseProgram(p);
    return p;
}

static const char *kVs =
    "#version 300 es\nin vec2 p; in vec2 a; out vec2 v;\n"
    "void main(){ v = a; gl_Position = vec4(p, 0.0, 1.0); }\n";

static const float kQuad[] = {-1, -1, 1, -1, -1, 1, 1, 1};

static void quad(void)
{
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, kQuad);
}

static void report(const char *name, const char *expect)
{
    unsigned char px[4] = {0};
    glReadPixels(4, 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("gltext %-34s read %3u %3u %3u %3u expect %s error 0x%x\n", name, px[0], px[1],
           px[2], px[3], expect, glGetError());
}

static GLuint texture(void)
{
    GLuint t;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    return t;
}

static void sampleQuad(const char *fsBody)
{
    char fs[512];
    snprintf(fs, sizeof fs,
             "#version 300 es\nprecision mediump float; uniform sampler2D t; in vec2 v; out vec4 o;\n"
             "void main(){ vec4 s = texture(t, vec2(0.5)); %s }\n", fsBody);
    program(kVs, fs);
    quad();
    glDisableVertexAttribArray(1);
    glClearColor(0, 0, 0, 0);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

int main(void)
{
    EGLDisplay d = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    eglInitialize(d, NULL, NULL);
    const EGLint ca[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
                         EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
                         EGL_NONE};
    EGLConfig c;
    EGLint n = 0;
    if (!eglChooseConfig(d, ca, &c, 1, &n) || n < 1) { printf("gltext no config\n"); return 1; }
    const EGLint sa[] = {EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE};
    EGLSurface s = eglCreatePbufferSurface(d, c, sa);
    const EGLint xa[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLContext x = eglCreateContext(d, c, EGL_NO_CONTEXT, xa);
    if (!eglMakeCurrent(d, s, s, x)) { printf("gltext no context\n"); return 1; }
    printf("gltext GL %s | %s | %s\n", glGetString(GL_VENDOR), glGetString(GL_RENDERER),
           glGetString(GL_VERSION));
    glViewport(0, 0, 16, 16);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);

    unsigned char rgba[4 * 16];
    for (int i = 0; i < 16; ++i) memcpy(rgba + 4 * i, "\xc8\x64\x32\xff", 4);
    unsigned char one[64];
    memset(one, 200, sizeof one);

    texture();
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 4, 4, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    sampleQuad("o = s;");
    report("RGBA8 teximage", "200 100 50 255");

    texture();
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, 4, 4, 0, GL_RED, GL_UNSIGNED_BYTE, one);
    sampleQuad("o = vec4(s.r, s.g, s.b, s.a);");
    report("R8 teximage (r g b a)", "200 0 0 255");

    texture();
    glTexStorage2D(GL_TEXTURE_2D, 1, GL_R8, 4, 4);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 4, 4, GL_RED, GL_UNSIGNED_BYTE, one);
    sampleQuad("o = vec4(s.r, 0.0, 0.0, 1.0);");
    report("R8 storage + subimage", "200 0 0 255");

    texture();
    glTexStorage2D(GL_TEXTURE_2D, 1, GL_R8, 5, 3);
    unsigned char zero[15] = {0};
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 5, 3, GL_RED, GL_UNSIGNED_BYTE, zero);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 1, 1, 3, 1, GL_RED, GL_UNSIGNED_BYTE, one);
    sampleQuad("o = vec4(s.r, 0.0, 0.0, 1.0);");
    report("R8 5x3 odd-width partial update", "200 0 0 255");

    texture();
    glTexImage2D(GL_TEXTURE_2D, 0, GL_ALPHA, 4, 4, 0, GL_ALPHA, GL_UNSIGNED_BYTE, one);
    sampleQuad("o = vec4(s.r, s.g, s.b, s.a);");
    report("ALPHA teximage (r g b a)", "0 0 0 200");

    texture();
    glTexImage2D(GL_TEXTURE_2D, 0, GL_LUMINANCE, 4, 4, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, one);
    sampleQuad("o = vec4(s.r, s.g, s.b, s.a);");
    report("LUMINANCE teximage (r g b a)", "200 200 200 255");

    // Skia's glyph quads: unnormalized ushort2 atlas coordinates.
    program(kVs, "#version 300 es\nprecision mediump float; in vec2 v; out vec4 o;\n"
                 "void main(){ o = vec4(v.x / 255.0, v.y / 255.0, 0.0, 1.0); }\n");
    quad();
    unsigned short coords[8] = {200, 100, 200, 100, 200, 100, 200, 100};
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 2, GL_UNSIGNED_SHORT, GL_FALSE, 0, coords);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    report("ushort2 attribute, client memory", "200 100 0 255");

    GLuint vb;
    glGenBuffers(1, &vb);
    glBindBuffer(GL_ARRAY_BUFFER, vb);
    glBufferData(GL_ARRAY_BUFFER, sizeof coords, coords, GL_STATIC_DRAW);
    glVertexAttribPointer(1, 2, GL_UNSIGNED_SHORT, GL_FALSE, 0, 0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    report("ushort2 attribute, buffer", "200 100 0 255");

    // A glyph draw: R8 coverage atlas addressed by ushort2 texels, color times
    // coverage blended over white with (ONE, ONE_MINUS_SRC_ALPHA).
    program("#version 300 es\nin vec2 p; in vec2 a; out vec2 v; uniform vec2 inv;\n"
            "void main(){ v = a * inv; gl_Position = vec4(p, 0.0, 1.0); }\n",
            "#version 300 es\nprecision mediump float; uniform sampler2D t; in vec2 v; out vec4 o;\n"
            "void main(){ float c = texture(t, v).r; o = vec4(0.0, 0.0, 0.0, 1.0) * c; }\n");
    GLuint glyph = texture();
    (void)glyph;
    glTexStorage2D(GL_TEXTURE_2D, 1, GL_R8, 256, 256);
    static unsigned char atlas[256 * 256];
    memset(atlas, 255, sizeof atlas);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 256, 256, GL_RED, GL_UNSIGNED_BYTE, atlas);
    GLint inv = glGetUniformLocation(0, "inv");
    GLint current = 0;
    glGetIntegerv(GL_CURRENT_PROGRAM, &current);
    inv = glGetUniformLocation(current, "inv");
    glUniform2f(inv, 1.0f / 256, 1.0f / 256);
    quad();
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 2, GL_UNSIGNED_SHORT, GL_FALSE, 0, coords);
    glClearColor(1, 1, 1, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glDisable(GL_BLEND);
    report("glyph quad over white", "0 0 0 255");
    return 0;
}
