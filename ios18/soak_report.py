#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Summarize a soak run from the app's statistics lines.

Usage: soak_report.py <console file> <first line> <last line> <out json>

The app prints "Andarium stats: cpu=N% fps=N ... held=N" every few seconds;
fps counts the frames the app presented in the last interval, so it reads 0
when Android draws nothing new and up to the display rate while it animates.
"""
import json
import re
import statistics
import sys

console, first, last, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
pattern = re.compile(r"Andarium stats: cpu=(\d+)% fps=(\d+) .* held=(\d+)")
lines = open(console, errors="replace").read().splitlines()[first:last]
samples = []
for line in lines:
    match = pattern.search(line)
    if match:
        samples.append(tuple(int(value) for value in match.groups()))
inactive = sum("Andarium: application inactive" in line for line in lines)
returned = [line for line in lines if "Andarium: runtime returned" in line]


def summary(values):
    if not values:
        return None
    ordered = sorted(values)
    return {
        "samples": len(values),
        "median": statistics.median(values),
        "p10": ordered[max(0, len(ordered) // 10)],
        "min": ordered[0],
        "max": ordered[-1],
    }


# Samples while Android animated (fps above 2) are the load the flings make.
moving = [sample for sample in samples if sample[1] > 2]
report = {
    "stat_samples": len(samples),
    "fps_while_moving": summary([sample[1] for sample in moving]),
    "share_of_samples_moving": round(len(moving) / len(samples), 2) if samples else None,
    "cpu_percent": summary([sample[0] for sample in samples]),
    "memory_held_mib_first_last_max": [samples[0][2], samples[-1][2], max(s[2] for s in samples)] if samples else None,
    "application_inactive_events": inactive,
    "runtime_returned": returned,
}
json.dump(report, open(out, "w"), indent=1)
print("SOAK REPORT", json.dumps(report))
