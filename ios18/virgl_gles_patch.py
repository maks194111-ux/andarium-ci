#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Declare integer vertex inputs as integers when the host is OpenGL ES.

virglrenderer writes every vertex shader input as `vec4` unless the host's
vendor is "ARM" (or VIRGL_USE_INTEGER is set), and reads integer attributes
with floatBitsToUint(). OpenGL ES (here ANGLE on Metal) converts an integer
attribute bound to a float input by value, not by bits, so Skia's glyph atlas
coordinates (unsigned 16-bit) become garbage: small text vanishes and large
text draws as gray boxes. On an ES host, always use the integer declarations.
"""
import sys
from pathlib import Path

OLD = (
    "static bool use_integer(void) {\n"
    "   if (getenv(\"VIRGL_USE_INTEGER\"))\n"
    "      return true;\n"
)
NEW = (
    "static bool use_integer(void) {\n"
    "   if (getenv(\"VIRGL_USE_INTEGER\"))\n"
    "      return true;\n"
    "   /* Andarium: an ES host converts integer attributes bound to float\n"
    "    * inputs by value; declare them as integers. */\n"
    "   if (vrend_state.use_gles)\n"
    "      return true;\n"
)

# The integer masks are only filled where the host has GLES 3.1 vertex
# attribute binding; ANGLE's Metal backend offers ES 3.0. Fill them when the
# vertex elements are created instead.
OLD_MASK = (
    "      v->elements[i].type = type;\n"
    "      if (desc->channel[0].normalized)\n"
)
NEW_MASK = (
    "      v->elements[i].type = type;\n"
    "      if (vrend_state.use_gles) {\n"
    "         UPDATE_INT_SIGN_MASK(elements[i].src_format, i,\n"
    "                              v->signed_int_bitmask,\n"
    "                              v->unsigned_int_bitmask);\n"
    "      }\n"
    "      if (desc->channel[0].normalized)\n"
)

path = Path(sys.argv[1]) / "src/vrend/vrend_renderer.c"
text = path.read_text()
for name, old, new in (("use_integer()", OLD, NEW), ("vertex element masks", OLD_MASK, NEW_MASK)):
    if text.count(new) == 1:
        print(f"virglrenderer: {name} already patched")
    elif text.count(old) == 1:
        text = text.replace(old, new)
        print(f"virglrenderer: {name} patched")
    else:
        raise SystemExit(f"virglrenderer: {name} not found")
path.write_text(text)
