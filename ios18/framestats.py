#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Where an application frame's time goes: stage medians from the output of
`dumpsys gfxinfo <package> framestats` (the last frames the app drew).

Usage: framestats.py <label> <file>
"""
import statistics
import sys

label, path = sys.argv[1], sys.argv[2]
rows, header = [], None
for line in open(path, errors="replace"):
    line = line.strip().rstrip(",")
    if line.startswith("Flags,"):
        header = line.split(",")
        continue
    if header and line and line[0].isdigit():
        cells = line.split(",")
        if len(cells) >= len(header):
            row = dict(zip(header, (int(c) for c in cells[:len(header)])))
            if row["Flags"] == 0 and row["FrameCompleted"] > row["IntendedVsync"]:
                rows.append(row)
    elif header and line.startswith("---"):
        header = None
if not rows:
    print(f"{label}: no frame rows")
    sys.exit(0)


def span(first, last):
    return [(r[last] - r[first]) / 1e6 for r in rows if first in r and last in r and r[last] and r[first]]


def field(name):
    return [r[name] / 1e6 for r in rows if name in r]


stages = [
    ("vsync to start of the app's work", span("IntendedVsync", "HandleInputStart")),
    ("UI thread (input, animation, layout, record)", span("HandleInputStart", "SyncQueued")),
    ("waiting for the render thread", span("SyncQueued", "SyncStart")),
    ("sync to the render thread", span("SyncStart", "IssueDrawCommandsStart")),
    ("issuing draw commands", span("IssueDrawCommandsStart", "SwapBuffers")),
    ("swap buffers", span("SwapBuffers", "FrameCompleted")),
    ("  of it: dequeue buffer", field("DequeueBufferDuration")),
    ("  of it: queue buffer", field("QueueBufferDuration")),
    ("whole frame (vsync to completed)", span("IntendedVsync", "FrameCompleted")),
    ("GPU completed after vsync", span("IntendedVsync", "GpuCompleted")),
    ("shown on the display after vsync", span("IntendedVsync", "DisplayPresentTime")),
]
print(f"{label}: {len(rows)} frames, milliseconds (median / p90 / p95 / p99 / maximum)")
for name, values in stages:
    values = sorted(v for v in values if v >= 0)
    if not values:
        continue
    quantiles = [values[min(len(values) - 1, int(len(values) * p))] for p in (.9, .95, .99)]
    print(f"  {name:46s} " + " / ".join(f"{v:7.2f}" for v in [statistics.median(values), *quantiles, max(values)]))
