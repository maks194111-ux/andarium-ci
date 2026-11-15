#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Say why the guest's address window could not be reserved, and let the same
device runtime start inside the iOS Simulator.

Two changes to darwin/runtime/native_kernel_layout.cpp:
  1. when the reservation fails, the log names the address asked for, what the
     system answered and the error, instead of only the size;
  2. a process inside the iOS Simulator is a macOS process, like an iOS app on
     a Mac, so it takes the placement upstream already uses there.  A phone
     never has SIMULATOR_UDID in its environment, so its placement is
     unchanged.
Every replacement must match exactly once, or the script fails.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
path = root / "darwin/runtime/native_kernel_layout.cpp"
text = path.read_text()


def replace(old: str, new: str) -> None:
    global text
    if text.count(old) != 1:
        raise SystemExit(f"native_kernel_layout: expected one match for {old[:60]!r}, found {text.count(old)}")
    text = text.replace(old, new)


replace("#include <cstdio>\n", "#include <cerrno>\n#include <cstdio>\n#include <cstdlib>\n")
replace("\tif (::uml::platform::running_ios_app_on_macos()) {\n",
        "\tif (::uml::platform::running_ios_app_on_macos() ||\n"
        "\t    (std::getenv(\"SIMULATOR_UDID\") != nullptr &&\n"
        "\t     std::getenv(\"UML_SIMULATOR_DEVICE_WINDOW\") == nullptr)) {\n")
replace("\tvoid *reserved = mmap(reinterpret_cast<void *>(geometry.window_start),\n"
        "\t\treservation, PROT_NONE, MAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1,\n"
        "\t\t0);\n",
        "\tvoid *reserved = mmap(reinterpret_cast<void *>(geometry.window_start),\n"
        "\t\treservation, PROT_NONE, MAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1,\n"
        "\t\t0);\n"
        "\tconst void *const first_answer = reserved;\n"
        "\tconst int first_error = reserved == MAP_FAILED ? errno : 0;\n")
replace("\tif (reserved == MAP_FAILED)\n\t\treturn {};\n"
        "\tconst auto base = reinterpret_cast<std::uintptr_t>(reserved);\n",
        "\tif (reserved == MAP_FAILED) {\n"
        "\t\tstd::fprintf(stderr,\n"
        "\t\t\t\"UML: window of %zu bytes: asked for %p, got %p (error %d), then error %d\\n\",\n"
        "\t\t\treservation, reinterpret_cast<void *>(geometry.window_start),\n"
        "\t\t\tfirst_answer, first_error, errno);\n"
        "\t\treturn {};\n"
        "\t}\n"
        "\tconst auto base = reinterpret_cast<std::uintptr_t>(reserved);\n")
replace("\t    base < DARWIN_UML_NATIVE_LINK_ADDRESS) {\n\t\tmunmap(reserved, reservation);\n",
        "\t    base < DARWIN_UML_NATIVE_LINK_ADDRESS) {\n"
        "\t\tstd::fprintf(stderr,\n"
        "\t\t\t\"UML: window of %zu bytes: asked for %p, got %p, then %p, which is below the kernel's address\\n\",\n"
        "\t\t\treservation, reinterpret_cast<void *>(geometry.window_start),\n"
        "\t\t\tfirst_answer, reserved);\n"
        "\t\tmunmap(reserved, reservation);\n")
path.write_text(text)
print("address window: failures are explained; Simulator hosts take the Mac placement")
