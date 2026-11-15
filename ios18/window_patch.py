#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Say why the guest's address window could not be reserved, and let the same
device runtime start inside the iOS Simulator.

Two changes to darwin/runtime/native_kernel_layout.cpp:
  1. when the reservation fails, the log names the address asked for, what the
     system answered and the error, instead of only the size;
  2. when the system does not give the address asked for, the window is asked
     for at several addresses above the kernel's own before "anywhere".  An
     unhinted answer is usually low, and upstream then gives up; that is what
     happens inside the iOS Simulator.  A host that gives the first address
     (the established layout) is unaffected.
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


replace("#include <cstdio>\n", "#include <cerrno>\n#include <cstdio>\n")
replace("\tvoid *reserved = mmap(reinterpret_cast<void *>(geometry.window_start),\n"
        "\t\treservation, PROT_NONE, MAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1,\n"
        "\t\t0);\n",
        "\tvoid *reserved = mmap(reinterpret_cast<void *>(geometry.window_start),\n"
        "\t\treservation, PROT_NONE, MAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1,\n"
        "\t\t0);\n"
        "\tconst void *const first_answer = reserved;\n"
        "\tconst int first_error = reserved == MAP_FAILED ? errno : 0;\n")
replace("\t\tmunmap(reserved, reservation);\n"
        "\t\treserved = placement == WindowPlacement::exact ? MAP_FAILED :\n"
        "\t\t\tmmap(nullptr, reservation, PROT_NONE,\n"
        "\t\t\t\tMAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1, 0);\n",
        "\t\tmunmap(reserved, reservation);\n"
        "\t\treserved = MAP_FAILED;\n"
        "\t\tif (placement != WindowPlacement::exact) {\n"
        "\t\t\t/* Ask above the kernel's address before asking anywhere:\n"
        "\t\t\t * an unhinted answer is usually low, and a low window\n"
        "\t\t\t * cannot hold the kernel. */\n"
        "\t\t\tconstexpr std::uintptr_t gib = std::uintptr_t{1} << 30;\n"
        "\t\t\tconst std::uintptr_t hints[] {\n"
        "\t\t\t\tgeometry.window_start + 2U * gib,\n"
        "\t\t\t\tgeometry.window_start + 4U * gib,\n"
        "\t\t\t\t64U * gib, 128U * gib, 256U * gib, 1024U * gib, 0,\n"
        "\t\t\t};\n"
        "\t\t\tfor (const auto hint : hints) {\n"
        "\t\t\t\tvoid *const answer = mmap(\n"
        "\t\t\t\t\treinterpret_cast<void *>(hint), reservation,\n"
        "\t\t\t\t\tPROT_NONE,\n"
        "\t\t\t\t\tMAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1, 0);\n"
        "\t\t\t\tif (answer == MAP_FAILED)\n"
        "\t\t\t\t\tcontinue;\n"
        "\t\t\t\tconst auto where =\n"
        "\t\t\t\t\treinterpret_cast<std::uintptr_t>(answer);\n"
        "\t\t\t\tif (hint == 0 ||\n"
        "\t\t\t\t    ((where & (DARWIN_UML_GUEST_PAGE_SIZE - 1U)) == 0U &&\n"
        "\t\t\t\t     where >= DARWIN_UML_NATIVE_LINK_ADDRESS)) {\n"
        "\t\t\t\t\treserved = answer;\n"
        "\t\t\t\t\tstd::fprintf(stderr,\n"
        "\t\t\t\t\t\t\"UML: window placed at %p (asked %p first, got %p)\\n\",\n"
        "\t\t\t\t\t\tanswer,\n"
        "\t\t\t\t\t\treinterpret_cast<void *>(geometry.window_start),\n"
        "\t\t\t\t\t\tfirst_answer);\n"
        "\t\t\t\t\tbreak;\n"
        "\t\t\t\t}\n"
        "\t\t\t\tmunmap(answer, reservation);\n"
        "\t\t\t}\n"
        "\t\t}\n")
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
# The address the geometry names is a multiple of the guest's 4 KiB page, and
# an Apple host maps whole 16 KiB pages: it answers with the next host page,
# a few kibibytes higher.  That answer holds the window as well as the exact
# one, so it is kept instead of being handed back.
replace("\t\tmunmap(reserved, reservation);\n"
        "\t\treserved = MAP_FAILED;\n"
        "\t\tif (placement != WindowPlacement::exact) {\n",
        "\t\tconst auto first_where = reinterpret_cast<std::uintptr_t>(reserved);\n"
        "\t\tconst bool beside = placement != WindowPlacement::exact &&\n"
        "\t\t\t(first_where & (DARWIN_UML_GUEST_PAGE_SIZE - 1U)) == 0U &&\n"
        "\t\t\tfirst_where > geometry.window_start &&\n"
        "\t\t\tfirst_where - geometry.window_start < 0x10000U;\n"
        "\t\tif (beside) {\n"
        "\t\t\tstd::fprintf(stderr,\n"
        "\t\t\t\t\"UML: window placed at %p, the host page after %p\\n\",\n"
        "\t\t\t\treserved, reinterpret_cast<void *>(geometry.window_start));\n"
        "\t\t} else {\n"
        "\t\t\tmunmap(reserved, reservation);\n"
        "\t\t\treserved = MAP_FAILED;\n"
        "\t\t}\n"
        "\t\tif (!beside && placement != WindowPlacement::exact) {\n")
# A failed first mmap must also reach the alternate-address search. Previously
# only a successful mapping at the wrong address did, so ENOMEM at the first
# hint skipped every fallback. Exact-placement kernels still fail closed.
replace("if (reserved != MAP_FAILED &&\n"
        "\t    reinterpret_cast<std::uintptr_t>(reserved) != geometry.window_start) {\n",
        "if (reserved == MAP_FAILED ||\n"
        "\t    reinterpret_cast<std::uintptr_t>(reserved) != geometry.window_start) {\n")
replace("\t\t\tmunmap(reserved, reservation);\n"
        "\t\t\treserved = MAP_FAILED;\n",
        "\t\t\tif (reserved != MAP_FAILED)\n"
        "\t\t\t\tmunmap(reserved, reservation);\n"
        "\t\t\treserved = MAP_FAILED;\n")
path.write_text(text)
print("address window: failures are explained; higher addresses are tried before giving up")
