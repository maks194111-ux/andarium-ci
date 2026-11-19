# SPDX-License-Identifier: MIT
"""Processor time by guest process and thread between two snapshots of /proc/*/task/*/stat."""
import re, sys
before, after, names = sys.argv[1:4]
def load(path):
    out = {}
    for line in open(path, errors="replace"):
        m = re.match(r"(\d+) \((.*)\) \S (.*)", line)
        if not m: continue
        f = m.group(3).split()
        if len(f) < 16: continue
        out[int(m.group(1))] = (m.group(2), int(f[10]), int(f[11]), int(f[15]))
    return out
a, b = load(before), load(after)
owner = {}
for line in open(names, errors="replace"):
    f = line.split()
    if len(f) >= 3 and f[0].isdigit() and f[1].isdigit():
        owner[int(f[1])] = (int(f[0]), f[2])
proc, threads, total_u, total_s, niced = {}, [], 0, 0, 0
for tid, (comm, u, s, nice) in b.items():
    u0, s0 = a.get(tid, (comm, 0, 0, 0))[1:3]
    du, ds = u - u0, s - s0
    if du + ds <= 0: continue
    pid, name = owner.get(tid, (0, "(ended or unknown)"))
    p = proc.setdefault((pid, name), [0, 0])
    p[0] += du; p[1] += ds
    total_u += du; total_s += ds
    if nice > 0: niced += du + ds
    threads.append((du + ds, du, ds, nice, name, comm))
print(f"threads that ran: user {total_u} + system {total_s} ticks; at low priority {niced}")
print("by process (user+system ticks):")
for (pid, name), (u, s) in sorted(proc.items(), key=lambda x: -sum(x[1]))[:16]:
    print(f"  {u + s:6d}  user {u:5d} system {s:5d}  {name}")
print("by thread:")
for t, u, s, nice, name, comm in sorted(threads, reverse=True)[:28]:
    print(f"  {t:6d}  user {u:5d} system {s:5d}  nice {nice:3d}  {name} / {comm}")
