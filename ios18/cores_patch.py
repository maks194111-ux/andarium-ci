#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Give the guest one processor per performance core, not per core.

Upstream gives a guest min(8, physical cores) processors.  On a chip with
efficiency cores (an iPad Pro M2 has 4 + 4) the guest's scheduler treats all
of them alike and runs foreground work on processors that the host places on
slow cores.  On the hosted Mac, more guest processors than cores made launches
several times slower.  The limit also brings a stored count down on load.

Not measured on a device.

Usage: cores_patch.py <upstream root>
"""
import sys
from pathlib import Path

path = Path(sys.argv[1]) / "GuestHost/Sources/GuestProcessorLimit.swift"
text = path.read_text()
old = """            UInt32(clamping: max(physicalProcessorCount, 1))
"""
new = """            UInt32(clamping: max(performanceCores(of: physicalProcessorCount), 1))
"""
anchor = """nonisolated enum GuestProcessorLimit {
"""
helper = anchor + """    /// The performance cores among `count` cores; four at most where the
    /// system does not say.
    static func performanceCores(of count: Int) -> Int {
        var fast: Int32 = 0
        var size = MemoryLayout<Int32>.size
        if sysctlbyname("hw.perflevel0.physicalcpu", &fast, &size, nil, 0) == 0, fast > 0 {
            return min(Int(fast), count)
        }
        return min(count, 4)
    }

"""
for piece in (old, anchor):
    if text.count(piece) != 1:
        raise SystemExit(f"GuestProcessorLimit.swift: expected one match for {piece[:50]!r}")
path.write_text(text.replace(old, new).replace(anchor, helper))
