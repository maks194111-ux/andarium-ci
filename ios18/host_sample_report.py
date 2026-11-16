#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Where the guest processor threads are in a macOS `sample` call graph.

Prints, per uml-vcpu thread, the share of samples in each leaf group: waiting
for the mappings lock (yield), stopped for a mapping change (ulock), idle,
native kernel code, and the rest.

Usage: host_sample_report.py <sample output>
"""
import re
import sys
from collections import defaultdict

lines = open(sys.argv[1], errors="replace").read().split("\n")
start = next(i for i, line in enumerate(lines) if line.startswith("Call graph:"))
end = next(i for i, line in enumerate(lines) if line.startswith("Total number in stack"))
pattern = re.compile(r"^([ +!:|]*)(\d+) (.*)$")
nodes = [(len(m.group(1)), int(m.group(2)), m.group(3))
         for m in map(pattern.match, lines[start + 1:end]) if m]
stack, thread, groups, totals = [], "", defaultdict(lambda: defaultdict(int)), {}
for index, (depth, count, name) in enumerate(nodes):
    while stack and stack[-1][0] >= depth:
        stack.pop()
    stack.append((depth, name))
    if name.startswith("Thread_"):
        thread = name[:44]
        totals[thread] = count
    following = nodes[index + 1][0] if index + 1 < len(nodes) else 0
    if following > depth or "vcpu" not in thread:
        continue
    entry = next((re.sub(r"\(.*", "", n).strip()[:48] for _, n in stack
                  if n.startswith("darwin_uml_")), "")
    if "swtch_pri" in name or "cthread_yield" in name or "sched_yield" in name:
        group = "lock wait (yield) in " + entry
    elif "__ulock_wait" in name:
        group = "stopped (ulock) in " + entry
    elif "pselect" in name or "poll" in name or "kevent" in name:
        group = "idle"
    elif name.startswith("???"):
        group = "native kernel or generated code"
    else:
        group = "engine code"
    groups[thread][group] += count
for thread, parts in groups.items():
    total = totals[thread]
    print(f"{thread}: {total} samples")
    for group, count in sorted(parts.items(), key=lambda item: -item[1])[:10]:
        print(f"   {100 * count / total:5.1f}%  {group}")
