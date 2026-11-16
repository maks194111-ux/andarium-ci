#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Summarize the ABBA run without turning hosted-Mac timings into iPad claims."""
import argparse
import json
import re
import statistics
from pathlib import Path


def read_frames(path):
    rows, header = [], None
    if not path.exists():
        return rows
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip().rstrip(",")
        if line.startswith("Flags,"):
            header = line.split(",")
        elif header and line and line[0].isdigit():
            cells = line.split(",")
            if len(cells) < len(header):
                continue
            try:
                row = dict(zip(header, map(int, cells)))
            except ValueError:
                continue
            if row.get("Flags") == 0 and 0 < row.get("FrameCompleted", 0) - row.get("IntendedVsync", 0) < 60_000_000_000:
                rows.append(row)
        elif line.startswith("---"):
            header = None
    return rows


def percentile(values, fraction):
    return sorted(values)[min(int(len(values) * fraction), len(values) - 1)]


def frames(path):
    rows = read_frames(path)
    if not rows:
        return {"count": 0}
    total = [(row["FrameCompleted"] - row["IntendedVsync"]) / 1e6 for row in rows]
    draws = [(row["SwapBuffers"] - row["IssueDrawCommandsStart"]) / 1e6
             for row in rows if row.get("SwapBuffers", 0) >= row.get("IssueDrawCommandsStart", 1) > 0]
    return {"count": len(total), "median_ms": statistics.median(total),
            "p90_ms": percentile(total, 0.9), "p99_ms": percentile(total, 0.99),
            "draw_median_ms": statistics.median(draws) if draws else None}


def resource_difference(directory):
    result = {}
    for tag in ("before", "after"):
        path = directory / f"resources-{tag}.txt"
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        result[tag] = {key: int(value) for key, value in
                       re.findall(r"^(MemTotal|MemAvailable|SwapTotal|SwapFree):\s+(\d+)", text, re.M)}
        # /proc/pressure files were emitted in cpu, memory, io order.
        result[tag]["psi_totals_us"] = [int(value) for value in re.findall(r"\btotal=(\d+)", text)]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--prefix", choices=("mapping", "aot"), default="mapping")
    args = parser.parse_args()
    output = {"environment": "Hosted macOS VM, Google image, 3 GiB RAM, 4 vCPUs, 828x1792, 60 Hz",
              "device_performance_measured": False, "profiles": {}, "comparisons": {}}
    if args.prefix == "aot":
        output["environment"] = "Hosted macOS VM, FIX9 vs full AOT/no ART JIT, 3 GiB, 4 vCPUs, 2048x2732, 60 Hz"
    for name in ("A1", "B1", "B2", "A2"):
        directory = args.report / f"{args.prefix}-{name}"
        output["profiles"][name] = {
            "settings": frames(directory / "framestats-settings.txt"),
            "systemui": frames(directory / "framestats-systemui.txt"),
            "resources": resource_difference(directory),
            "telegram_installed": "Success" in (directory / "telegram-install.txt").read_text()
            if (directory / "telegram-install.txt").exists() else None,
            "telegram_launch": (directory / "telegram-start.txt").read_text(errors="replace")
            if (directory / "telegram-start.txt").exists() else None,
            "telegram_alive": (directory / "telegram-alive.txt").read_text(errors="replace")
            if (directory / "telegram-alive.txt").exists() else None,
        }
    for app in ("settings", "systemui"):
        pairs = []
        for baseline, candidate in (("A1", "B1"), ("A2", "B2")):
            a = output["profiles"][baseline][app]
            b = output["profiles"][candidate][app]
            if min(a["count"], b["count"]) >= 30:
                pairs.append({metric: 100 * (a[metric] - b[metric]) / a[metric]
                              for metric in ("median_ms", "p90_ms") if a[metric] > 0})
        output["comparisons"][app] = {
            "pairs_improvement_percent": pairs,
            "consistent_median_and_p90_gain": len(pairs) == 2 and all(
                pair.get(metric, 0) > 5 for pair in pairs for metric in ("median_ms", "p90_ms")),
        }
    output["interpretation"] = (
        "Positive percentages mean shorter frame duration, not an FPS multiplier. "
        "A consistent result is a screening signal only, not proof of iPad performance. "
        "Missing/insufficient frames do not pass. No physical touch-to-display latency was measured."
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
