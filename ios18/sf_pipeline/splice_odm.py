#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Copy an Android release directory with its odm partition replaced.

The replacement odm image (odm-sfpipeline.img) is the release's own odm
filesystem rebuilt with every inode's owner, mode and labels kept; only
etc/build.prop differs (odm-build.prop: SurfaceFlinger work durations).
Every other partition is copied byte for byte and its SHA-256 is checked
against the release's partition layout before and after.
Usage: splice_odm.py <release> <new release> <odm image> [expected odm sha256]
"""
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gpt_disk import assemble, digest, verify  # noqa: E402

source, target, odm = (Path(p) for p in sys.argv[1:4])
expected = sys.argv[4] if len(sys.argv) > 4 else None
layout = json.loads((source / "guest/partition-layout.json").read_text())
original = copy.deepcopy(layout)
verify(layout, source / "guest/system.img")
shutil.copytree(source, target, ignore=shutil.ignore_patterns("system.img"))
with tempfile.TemporaryDirectory(dir=target) as scratch:
    images = {}
    with (source / "guest/system.img").open("rb") as disk:
        for part in layout["system_disk"]["partitions"]:
            if part["name"] == "odm":
                if expected and part["sha256"] != expected:
                    raise SystemExit(f"odm is not the expected original: {part['sha256']}")
                images["odm"] = odm
                continue
            image = Path(scratch) / (part["name"] + ".img")
            disk.seek(part["start_bytes"])
            remaining = part["image_bytes"]
            with image.open("xb") as out:
                while remaining:
                    data = disk.read(min(remaining, 4 << 20))
                    if not data:
                        raise SystemExit("short read from the system disk")
                    out.write(data)
                    remaining -= len(data)
            images[part["name"]] = image
    assemble(layout, images, target / "guest/system.img")
for part, before in zip(layout["system_disk"]["partitions"],
                        original["system_disk"]["partitions"]):
    if part["name"] != "odm" and part["sha256"] != before["sha256"]:
        raise SystemExit(f"partition changed: {part['name']}")
text = (json.dumps(layout, indent=2) + "\n").encode()
(target / "guest/partition-layout.json").write_bytes(text)
manifest = json.loads((target / "release-manifest.json").read_text())
for entry in manifest["inventory"]:
    if entry["path"] == "guest/system.img":
        entry["size"] = (target / "guest/system.img").stat().st_size
    elif entry["path"] == "guest/partition-layout.json":
        entry["size"] = len(text)
(target / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("odm replaced:", digest(odm), "disk", layout["system_disk"]["sha256"])
