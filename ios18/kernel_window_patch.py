#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Make the guest's address window smaller for the same guest memory.

A device report (iPad Pro M2, iPadOS 27.1): the system grants a 5 GiB address
window but not a 7 GiB one, so Android could have 2 GiB of memory and no more.
The window is guest memory + an allowance for the kernel's own mappings
(vmalloc) + 1 GiB for shared device memory.  Upstream sizes the allowance like
the memory, between 1 and 4 GiB; it is address space, not memory.  This patch
fixes the allowance at its 1 GiB floor, so 3 GiB of memory needs 5 GiB of
addresses and 4 GiB needs 6.

The rule lives in two places that must agree:
  - the prebuilt guest kernel (get_top_address), changed here in its two
    instructions, each checked against the bytes expected;
  - the engine's CMake constant UML_NATIVE_AUXILIARY_MAXIMUM.
Usage: kernel_window_patch.py <upstream root> <kernel artifact directory>
"""
import struct
import sys
from pathlib import Path

root = Path(sys.argv[1])
artifact = Path(sys.argv[2])

symbols = {}
for line in (artifact / "kernel/System.map").read_text().splitlines():
    address, _, name = line.split(" ", 2)
    symbols.setdefault(name, int(address, 16))
function = symbols["get_top_address"]

path = artifact / "kernel/vmlinux"
image = bytearray(path.read_bytes())
header_offset = struct.unpack_from("<Q", image, 0x20)[0]
entry_size, count = struct.unpack_from("<HH", image, 0x36)
file_offset = None
for index in range(count):
    kind, _, offset, address, _, size, _, _ = struct.unpack_from(
        "<IIQQQQQQ", image, header_offset + index * entry_size)
    if kind == 1 and address <= function < address + size:
        file_offset = offset + function - address
if file_offset is None:
    raise SystemExit("get_top_address is in no loaded segment")

# tst x9, #-0x100000000 ; mov x9, #0x100000000 ; csel x9, x11, x9, eq
# (the allowance in x11 when it is below 4 GiB, else 4 GiB)
expected = [0xF2607D3F, 0xD2C00029, 0x9A89_0169]
# becomes: tst (unchanged) ; mov x9, #0x40000000 ; nop
replacement = [0xF2607D3F, 0xD2A80009, 0xD503201F]
found = None
for step in range(0, 0x80, 4):
    words = list(struct.unpack_from("<3I", image, file_offset + step))
    if words == expected:
        found = file_offset + step
    elif words == replacement:
        print("guest kernel already has the 1 GiB allowance")
        found = -1
if found is None:
    raise SystemExit("get_top_address: the allowance rule is not where expected")
if found >= 0:
    struct.pack_into("<3I", image, found, *replacement)
    path.write_bytes(image)

cmake = root / "CMakeLists.txt"
text = cmake.read_text()
old = "set(UML_NATIVE_AUXILIARY_MAXIMUM 0x0000000100000000ULL)"
new = "set(UML_NATIVE_AUXILIARY_MAXIMUM 0x0000000040000000ULL)"
if text.count(old) == 1:
    cmake.write_text(text.replace(old, new))
elif text.count(new) != 1:
    raise SystemExit("CMakeLists.txt: UML_NATIVE_AUXILIARY_MAXIMUM not found")
print("address window: guest memory + 2 GiB (kernel and engine agree)")
