#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replace the virtual-device product names in an Andarium release.

The property service does not allow odm to override ro.product.* or ro.system.*
values. Rebuild those owning EROFS partitions instead, preserving every tar
entry's owner, mode, timestamps and SELinux label. Only build.prop changes.

Usage: phone_identity.py <release> <fsck.erofs> <mkfs.erofs> <scratch dir>
The release is updated in place. Its ahead-of-time code must be rebuilt after.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).parent))
from gpt_disk import assemble, verify  # noqa: E402

release, fsck, mkfs, scratch_parent = map(Path, sys.argv[1:5])
disk_path = release / "guest/system.img"
layout_path = release / "guest/partition-layout.json"
manifest_path = release / "release-manifest.json"
layout = json.loads(layout_path.read_text())
original = copy.deepcopy(layout)
verify(layout, disk_path)

# system and vendor keep their main build.prop at different paths.
properties = {
    "system": ("system/build.prop", {
        "ro.product.system.brand": "Andarium",
        "ro.product.system.device": "andarium",
        "ro.product.system.manufacturer": "Kernarium",
        "ro.product.system.model": "Andarium Tab",
        "ro.product.system.name": "lineage_andarium",
        "ro.system.build.fingerprint":
            "Andarium/lineage_andarium/andarium:17/CP2A.260605.016/"
            "2026110817:user/release-keys",
    }),
    "product": ("etc/build.prop", {
        "ro.product.product.model": "Andarium Tab",
    }),
    "system_ext": ("etc/build.prop", {
        "ro.product.system_ext.model": "Andarium Tab",
    }),
    "vendor": ("build.prop", {
        "ro.product.vendor.model": "Andarium Tab",
    }),
}


def run(arguments, **kwargs):
    print("+", " ".join(map(str, arguments)), flush=True)
    subprocess.run(list(map(str, arguments)), check=True, **kwargs)


def extract_tar(image, root, archive):
    """fsck writes Android ownership/xattrs; archive them before dropping sudo."""
    run(["sudo", "-n", fsck, f"--extract={root}", "--xattrs", "--preserve", image])
    version = subprocess.run(["tar", "--version"], capture_output=True, text=True).stdout
    gnu = "GNU tar" in version
    command = ["sudo", "-n", "tar"]
    if gnu:
        command += ["--xattrs", "--xattrs-include=*", "--acls", "--selinux"]
    command += ["-cf", archive, "-C", root, "."]
    run(command)
    run(["sudo", "-n", "chown", f"{os.getuid()}:{os.getgid()}", archive])
    run(["sudo", "-n", "rm", "-rf", root])


def rewrite_properties(source, destination, member_name, updates):
    """Stream a large tar; only the small property file passes through memory."""
    found = set()
    with tarfile.open(source) as tin, tarfile.open(destination, "w", format=tarfile.PAX_FORMAT) as tout:
        for member in tin:
            name = member.name.removeprefix("./")
            if name != member_name:
                tout.addfile(member, tin.extractfile(member) if member.isfile() else None)
                continue
            # A non-root extraction silently loses exactly the metadata Android
            # needs. Fail here instead of producing an unbootable system image.
            assert member.uid == 0 and member.gid == 0, f"ownership was not preserved: {name}"
            label_keys = ("SCHILY.xattr.security.selinux", "LIBARCHIVE.xattr.security.selinux")
            assert any(key in member.pax_headers for key in label_keys), \
                f"SELinux label was not preserved: {name}"
            text = tin.extractfile(member).read().decode()
            lines = []
            for line in text.splitlines():
                key, separator, value = line.partition("=")
                if separator and key in updates:
                    assert key not in found, f"duplicate property: {name}: {key}"
                    found.add(key)
                    line = f"{key}={updates[key]}"
                lines.append(line)
            missing = set(updates) - found
            assert not missing, f"missing properties in {name}: {sorted(missing)}"
            data = ("\n".join(lines) + ("\n" if text.endswith("\n") else "")).encode()
            member.size = len(data)
            import io
            tout.addfile(member, io.BytesIO(data))
    print(f"properties changed in {member_name}: {', '.join(sorted(found))}", flush=True)


scratch = Path(tempfile.mkdtemp(prefix="phone-identity-", dir=scratch_parent))
try:
    images = {}
    with disk_path.open("rb") as disk:
        for part in original["system_disk"]["partitions"]:
            name = part["name"]
            image = scratch / f"{name}.img"
            disk.seek(part["start_bytes"])
            remaining = part["image_bytes"]
            with image.open("xb") as out:
                while remaining:
                    data = disk.read(min(remaining, 4 << 20))
                    assert data, f"short read from system disk: {name}"
                    out.write(data)
                    remaining -= len(data)
            if name not in properties:
                images[name] = image
                continue

            root = scratch / f"{name}-root"
            source_tar = scratch / f"{name}-original.tar"
            changed_tar = scratch / f"{name}-changed.tar"
            rebuilt = scratch / f"{name}-phone.img"
            extract_tar(image, root, source_tar)
            member_name, updates = properties[name]
            rewrite_properties(source_tar, changed_tar, member_name, updates)
            source_tar.unlink()
            run([mkfs, "--tar=f", "-zzstd", "-T", "1230768000", "--quiet", rebuilt, changed_tar])
            run([fsck, rebuilt])
            changed_tar.unlink()
            images[name] = rebuilt
            image.unlink()

    replacement = scratch / "system.img"
    assemble(layout, images, replacement)
    verify(layout, replacement)
    for part, before in zip(layout["system_disk"]["partitions"],
                            original["system_disk"]["partitions"]):
        if part["name"] not in properties:
            assert part["sha256"] == before["sha256"], f"partition changed: {part['name']}"

    os.replace(replacement, disk_path)
    layout_text = (json.dumps(layout, indent=2) + "\n").encode()
    layout_path.write_bytes(layout_text)
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["inventory"]:
        if entry["path"] == "guest/system.img":
            entry["size"] = disk_path.stat().st_size
        elif entry["path"] == "guest/partition-layout.json":
            entry["size"] = len(layout_text)
    customization = manifest.setdefault("customization", {})
    customization["device_identity"] = "Andarium Tab; product names only; not a certified physical device"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("phone identity installed; system disk", layout["system_disk"]["sha256"], flush=True)
finally:
    shutil.rmtree(scratch, ignore_errors=True)
