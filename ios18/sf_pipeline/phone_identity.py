#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replace the virtual-device product names in an Andarium release.

The property service does not allow odm to override ro.product.* or ro.system.*
values. Rebuild those owning EROFS partitions instead, preserving every tar
entry's owner, mode, timestamps and SELinux label. Update the same name in the
init_boot ramdisk. No executable, application, or protection code is changed.

Usage: phone_identity.py <release> <fsck.erofs> <mkfs.erofs> <scratch dir>
The release is updated in place. Its ahead-of-time code must be rebuilt after.
"""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).parent))
from gpt_disk import assemble, verify  # noqa: E402

# system and vendor keep their main build.prop at different paths.
PROPERTIES = {
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
    "product": ("etc/build.prop", {"ro.product.product.model": "Andarium Tab"}),
    "system_ext": ("etc/build.prop", {"ro.product.system_ext.model": "Andarium Tab"}),
    "vendor": ("build.prop", {"ro.product.vendor.model": "Andarium Tab"}),
}


def run(arguments, **kwargs):
    print("+", " ".join(map(str, arguments)), flush=True)
    subprocess.run(list(map(str, arguments)), check=True, **kwargs)


def extract_tar(image, root, archive, fsck):
    """fsck writes Android ownership/xattrs; archive them before dropping sudo."""
    run(["sudo", "-n", fsck, f"--extract={root}", "--xattrs", "--preserve", image])
    version = subprocess.run(["tar", "--version"], capture_output=True, text=True).stdout
    gnu = "GNU tar" in version
    if gnu:
        command = ["sudo", "-n", "tar"]
        # --xattrs includes the SELinux label; --selinux is not needed for that.
        command += ["--xattrs", "--xattrs-include=*", "--acls"]
    else:
        # macOS otherwise adds a phantom ._file beside every file with xattrs.
        # Its pax LIBARCHIVE.xattr keys retain the SELinux labels without them.
        command = ["sudo", "-n", "env", "COPYFILE_DISABLE=1", "tar"]
    command += ["-cf", archive, "-C", root, "."]
    run(command)
    run(["sudo", "-n", "chown", f"{os.getuid()}:{os.getgid()}", archive])
    run(["sudo", "-n", "rm", "-rf", root])


def edit_property_text(text, required_updates):
    """Change required keys and every product model still saying Virtual Device."""
    found = set()
    changed = []
    lines = []
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in required_updates:
            assert key not in found, f"duplicate property: {key}"
            found.add(key)
            line = f"{key}={required_updates[key]}"
            changed.append(key)
        elif (separator and value == "Andarium Virtual Device"
              and key.startswith("ro.product.") and key.endswith(".model")):
            line = f"{key}=Andarium Tab"
            changed.append(key)
        lines.append(line)
    missing = set(required_updates) - found
    assert not missing, f"missing properties: {sorted(missing)}"
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), changed


def check_android_metadata(member):
    """A non-root extraction silently loses what Android needs to boot."""
    name = member.name.removeprefix("./")
    assert member.uid == 0 and member.gid == 0, f"ownership was not preserved: {name}"
    label_keys = ("SCHILY.xattr.security.selinux", "LIBARCHIVE.xattr.security.selinux")
    assert any(key in member.pax_headers for key in label_keys), \
        f"SELinux label was not preserved: {name}"


def rewrite_properties(source, destination, member_name, updates):
    """Stream a large tar; only small property files pass through memory."""
    with tarfile.open(source) as tin, tarfile.open(destination, "w", format=tarfile.PAX_FORMAT) as tout:
        for member in tin:
            name = member.name.removeprefix("./")
            is_primary = name == member_name
            is_build_properties = name.endswith("build.prop") and member.isfile()
            if not is_build_properties:
                tout.addfile(member, tin.extractfile(member) if member.isfile() else None)
                continue
            check_android_metadata(member)
            text = tin.extractfile(member).read().decode()
            changed_text, changed = edit_property_text(text, updates if is_primary else {})
            if not changed:
                # Keep the original member bytes when there is nothing to change.
                tout.addfile(member, io.BytesIO(text.encode()))
                continue
            data = changed_text.encode()
            member.size = len(data)
            tout.addfile(member, io.BytesIO(data))
            print(f"properties changed in {name}: {', '.join(changed)}", flush=True)


def update_init_boot(image):
    """Edit build.prop in an unsigned v4 init_boot's uncompressed newc ramdisk."""
    original = image.read_bytes()
    assert original[:8] == b"ANDROID!", "init_boot magic is missing"
    kernel_size, ramdisk_size = struct.unpack_from("<II", original, 8)
    assert kernel_size == 0 and struct.unpack_from("<I", original, 40)[0] == 4
    assert 4096 + ramdisk_size <= len(original)
    ramdisk = original[4096:4096 + ramdisk_size]
    output = bytearray()
    offset = 0
    replacements = 0
    while ramdisk[offset:offset + 6] in (b"070701", b"070702"):
        header = ramdisk[offset:offset + 110]
        fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        file_size, name_size = fields[6], fields[11]
        name_start = offset + 110
        name = ramdisk[name_start:name_start + name_size - 1].decode()
        data_start = (name_start + name_size + 3) & ~3
        data_end = data_start + file_size
        next_offset = (data_end + 3) & ~3
        entry = bytearray(ramdisk[offset:next_offset])
        relative_data = data_start - offset
        if name == "system/etc/ramdisk/build.prop":
            text = ramdisk[data_start:data_end].decode()
            changed, keys = edit_property_text(text, {"ro.product.bootimage.model": "Andarium Tab"})
            data = changed.encode()
            entry[54:62] = f"{len(data):08x}".encode()
            entry[relative_data:] = data + b"\0" * ((-len(data)) & 3)
            replacements += 1
            print(f"properties changed in init_boot:{name}: {', '.join(keys)}", flush=True)
        output += entry
        offset = next_offset
        if name == "TRAILER!!!":
            break
    assert replacements == 1, "the init_boot product model was not found exactly once"
    assert offset <= len(ramdisk)
    output += ramdisk[offset:]
    assert len(output) <= ramdisk_size, "the replacement ramdisk grew unexpectedly"
    boot = bytearray(original)
    boot[4096:4096 + len(output)] = output
    boot[4096 + len(output):] = b"\0" * (len(original) - 4096 - len(output))
    struct.pack_into("<I", boot, 12, len(output))
    replacement = image.with_name("init_boot-phone.img")
    replacement.write_bytes(boot)
    assert len(replacement.read_bytes()) == len(original)
    return replacement


def main():
    release, fsck, mkfs, scratch_parent = map(Path, sys.argv[1:5])
    disk_path = release / "guest/system.img"
    layout_path = release / "guest/partition-layout.json"
    manifest_path = release / "release-manifest.json"
    layout = json.loads(layout_path.read_text())
    original = copy.deepcopy(layout)
    verify(layout, disk_path)
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
                if name == "init_boot":
                    images[name] = update_init_boot(image)
                    continue
                if name not in PROPERTIES:
                    images[name] = image
                    continue

                root = scratch / f"{name}-root"
                source_tar = scratch / f"{name}-original.tar"
                changed_tar = scratch / f"{name}-changed.tar"
                rebuilt = scratch / f"{name}-phone.img"
                extract_tar(image, root, source_tar, fsck)
                member_name, updates = PROPERTIES[name]
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
            if part["name"] not in PROPERTIES and part["name"] != "init_boot":
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


if __name__ == "__main__":
    main()
