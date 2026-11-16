#!/usr/bin/env python3
"""Wait for a screenshot checkpoint or test completion, without stopping the test."""
from pathlib import Path
import sys
import time

root = Path(sys.argv[1])
pattern = sys.argv[2]
deadline = time.monotonic() + 720
while time.monotonic() < deadline:
    images = sorted((root / "simulator-report").glob(pattern))
    if images:
        print("Screenshot checkpoint:", images[-1].name, flush=True)
        break
    # A fast boot starts the long soak before indices 03 or 06 are reached.
    # Skipping a missing progress image is safe only after ready AND an
    # earlier real Android screenshot. The final harness result still decides
    # success; this is not permission to turn a failed soak green.
    report = root / "simulator-report"
    console = report / "console-start.txt"
    if (pattern in ("03-start-*.png", "06-start-*.png")
            and console.exists()
            and "boot reached ready" in console.read_text(errors="replace")
            and any(report.glob("[0-9][0-9]-start-*.png"))):
        print("Android became ready before this optional screenshot; soak continues", flush=True)
        break
    if (root / "simulator.exit").exists():
        print("Test finished before this screenshot checkpoint", flush=True)
        break
    time.sleep(5)
else:
    raise SystemExit("No screenshot or completion marker within 12 minutes")
