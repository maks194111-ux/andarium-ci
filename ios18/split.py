#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Split an application's frame into guest processor time and waiting.

Reads two snapshots of per-thread scheduler counters taken around a scroll
(lines "<process> <thread name>|<tid> <run ns> <runqueue wait ns> <slices>"),
the number of frames drawn in between, and optional strace outputs.

Usage: split.py <label> <before> <after> <frames> <seconds> [strace -c file] [strace -T file]
"""
import collections
import re
import sys

label, before, after, frames, seconds = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4] or 0), float(sys.argv[5])


def load(path):
    table = {}
    for line in open(path, errors="replace"):
        match = re.match(r"(\S+) (.*)\|(\d+) (\d+) (\d+) (\d+)\s*$", line)
        if match:
            table[(match[1], match[3])] = (match[2], int(match[4]), int(match[5]), int(match[6]))
    return table


first, second = load(before), load(after)
rows = []
for key, (name, run, wait, slices) in second.items():
    if key in first:
        rows.append((run - first[key][1], wait - first[key][2], slices - first[key][3], key[0], name))
rows.sort(reverse=True)
print(f"{label}: {frames} frames in {seconds:.1f} s; busiest threads (per frame: on a processor / waiting for a processor / times scheduled)")
if frames:
    for run, wait, slices, process, name in rows[:12]:
        if run <= 0:
            continue
        print(f"  {process:16s} {name:18s} {run / frames / 1e6:6.2f} ms / {wait / frames / 1e6:6.2f} ms / {slices / frames:5.1f}")
    total = sum(r[0] for r in rows)
    print(f"  all listed threads together: {total / 1e9:.1f} processor-seconds in {seconds:.1f} s")
if not rows:
    print("  no scheduler counters (the kernel does not keep them)")

if len(sys.argv) > 6:
    print(f"{label}: render thread system calls (strace summary)")
    for line in open(sys.argv[6], errors="replace").read().splitlines()[:16]:
        print("  " + line[:120])
if len(sys.argv) > 7:
    calls = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for line in open(sys.argv[7], errors="replace"):
        match = re.search(r"(\w+)\((.*)<([0-9.]+)>\s*$", line)
        if not match:
            continue
        name = match[1]
        if name == "ioctl":
            request = re.match(r"\d+, ([^,)]+)", match[2])
            name = "ioctl " + (request[1] if request else "?")
        entry = calls[name]
        entry[0] += 1; entry[1] += float(match[3]); entry[2] = max(entry[2], float(match[3]))
    print(f"{label}: render thread calls with their duration (count, total ms, average ms, longest ms)")
    for name, (count, total, longest) in sorted(calls.items(), key=lambda item: -item[1][1])[:14]:
        print(f"  {name[:58]:58s} {count:6d} {total * 1e3:9.1f} {total / count * 1e3:7.3f} {longest * 1e3:7.2f}")
