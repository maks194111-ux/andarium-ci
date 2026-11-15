#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Guest RAM on devices with a small process memory limit (4 GiB phones).

Upstream never gives a new guest less than 1536 MiB, also where the process
limit does not leave room for that much beside the engine and the graphics
memory: there the guest starts above the line at which iOS is likely to end
the process, and the settings offer no smaller size.  With this patch such a
device gets the size that fits, down to 1024 MiB, and the settings offer
sizes from 1024 MiB.  Devices whose limit leaves 1536 MiB or more are
unchanged.

Usage: lowmem_patch.py <upstream root> engine|app   (the header is shared)
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
part = sys.argv[2]


def edit(relative: str, changes) -> None:
    path = root / relative
    text = path.read_text()
    for old, new in changes:
        if text.count(old) != 1:
            raise SystemExit(f"{relative}: expected one match for {old[:60]!r}, found {text.count(old)}")
        text = text.replace(old, new)
    path.write_text(text)


edit("darwin/runtime/guest_memory_budget.hpp", [
    ("""inline constexpr std::uint32_t default_guest_memory_step_mib = 512;
""",
     """inline constexpr std::uint32_t default_guest_memory_step_mib = 512;
/* Low-memory devices: where the limit leaves a guest less than
 * default_guest_memory_minimum_mib, a new guest gets what fits, on the 64 MiB
 * steps and no lower than this. */
inline constexpr std::uint32_t low_memory_guest_minimum_mib = 1024;
"""),
    ("""\tconst auto stepped = safe / default_guest_memory_step_mib *
\t\tdefault_guest_memory_step_mib;
\treturn std::min(std::max(stepped, default_guest_memory_minimum_mib),
\t\tmaximum);""",
     """\tconst auto stepped = safe / default_guest_memory_step_mib *
\t\tdefault_guest_memory_step_mib;
\tif (safe < default_guest_memory_minimum_mib)
\t\treturn std::min(std::max(safe, low_memory_guest_minimum_mib), maximum);
\treturn std::min(std::max(stepped, default_guest_memory_minimum_mib),
\t\tmaximum);"""),
])
if part == "app":
    edit("Andarium/AndariumCore/Sources/AndariumCore/Limits.swift", [
        ("public static let minimumMemoryMiB = 1536",
         "public static let minimumMemoryMiB = 1024"),
    ])
print(f"low-memory rule applied ({part})")
