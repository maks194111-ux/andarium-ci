#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""How busy each host thread of the emulator is, from a macOS `sample` graph.

Per thread: the share of samples not spent in a waiting primitive, and the
busiest leaf functions.  The sum over threads is the number of host processors
the emulator needs for the sampled work.

Usage: host_threads_report.py <sample output> [top leaves per thread]
"""
import re
import sys
from collections import defaultdict

WAITS = ("mach_msg", "__psynch_cvwait", "__psynch_mutexwait", "__ulock_wait", "kevent", "pselect",
         "__select", "poll", "__semwait", "semaphore_wait", "semaphore_timedwait", "__workq_kernreturn",
         "__sigwait", "read ", "__read", "recv", "__accept", "nanosleep", "usleep", "_dispatch_sig_thread",
         "__wait4", "start_wqthread", "__channel_get_info", "necp_client_action", "__sigsuspend")
lines = open(sys.argv[1], errors="replace").read().split("\n")
top = int(sys.argv[2]) if len(sys.argv) > 2 else 4
start = next(i for i, line in enumerate(lines) if line.startswith("Call graph:"))
end = next(i for i, line in enumerate(lines) if line.startswith("Total number in stack"))
pattern = re.compile(r"^([ +!:|]*)(\d+) (.*)$")
nodes = [(len(m.group(1)), int(m.group(2)), m.group(3))
         for m in map(pattern.match, lines[start + 1:end]) if m]
threads, order = {}, []
thread = None
for index, (depth, count, name) in enumerate(nodes):
    if name.startswith("Thread_"):
        thread = name[:70]
        threads[thread] = {"total": count, "busy": 0, "leaves": defaultdict(int)}
        order.append(thread)
        continue
    if thread is None:
        continue
    children = 0
    for later_depth, later_count, _ in nodes[index + 1:]:
        if later_depth <= depth:
            break
        if later_depth == depth + 2 or later_depth == depth + 1:
            children += later_count
    own = count - children
    if own <= 0:
        continue
    label = re.sub(r"\s+\[0x[0-9a-f,x]+\].*|\s+\+ \d+.*", "", name)[:70]
    if any(wait in name for wait in WAITS):
        continue
    threads[thread]["busy"] += own
    threads[thread]["leaves"][label] += own
samples = max((t["total"] for t in threads.values()), default=1)
total = sum(t["busy"] for t in threads.values())
print(f"threads: {len(threads)}; busy host processors (sum of busy shares): {total / samples:.2f}")
for name in sorted(order, key=lambda n: -threads[n]["busy"])[:14]:
    t = threads[name]
    if t["busy"] * 100 < samples:
        break
    leaves = sorted(t["leaves"].items(), key=lambda item: -item[1])[:top]
    print(f"  {100 * t['busy'] / samples:5.1f}%  {name}")
    for label, count in leaves:
        print(f"           {100 * count / samples:5.1f}%  {label}")
