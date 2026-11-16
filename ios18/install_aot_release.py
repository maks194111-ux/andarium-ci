"""Install precisely the four private experiment resources into a test app.

No filesystem traversal, symlinks, arbitrary extra resources or misleading
runtime claims. The producer already validated all GPT partitions and ART
outputs; the consumer separately verifies the entire downloaded disk hash.
"""
import hashlib
import json
import shutil
import stat
import sys
import zipfile
from pathlib import Path


def install(archive, destination, report):
    files = {"release-manifest.json", "boot/kernel-command-line.txt",
             "guest/partition-layout.json", "guest/system.img"}
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) != len(files) or {e.filename for e in entries} != files:
            raise ValueError("The release archive must contain exactly four known files")
        for entry in entries:
            if stat.S_ISLNK(entry.external_attr >> 16) or entry.file_size <= 0:
                raise ValueError("Invalid release resource")
            target = destination / entry.filename
            if target.is_symlink() or not target.parent.is_dir():
                raise ValueError("Unsafe or missing release destination")
            with z.open(entry) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out, 1 << 20)
    layout = json.loads((destination / "guest/partition-layout.json").read_text())
    checksum = hashlib.sha256()
    with (destination / "guest/system.img").open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            checksum.update(chunk)
    if checksum.hexdigest() != layout["system_disk"]["sha256"]:
        raise ValueError("The received system disk hash differs from its verified layout")
    manifest = json.loads((destination / "release-manifest.json").read_text())
    report.write_text(json.dumps(
        {"image_kind": "full_aot_no_art_jit_experiment",
         "release_id": manifest["release_id"], "sha256": checksum.hexdigest(),
         "download_integrity_verified": True, "device_performance_verified": False},
        indent=2) + "\n")
    print("AOT resources installed; downloaded disk hash verified; runtime not yet tested")


if __name__ == "__main__":
    install(*(Path(p) for p in sys.argv[1:]))
