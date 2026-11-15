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
    if (root / "simulator.exit").exists():
        print("Test finished before this screenshot checkpoint", flush=True)
        break
    time.sleep(5)
else:
    raise SystemExit("No screenshot or completion marker within 12 minutes")
