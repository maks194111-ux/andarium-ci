#!/usr/bin/env python3
"""Rebuild the odm image from the complete tar with extra properties and init files.
usage: make_odm.py <out.img> <props-to-append-file> [name=rcfile ...]"""
import io, subprocess, sys, tarfile
src = "../andarium-bgquiet/work/odm-complete.tar"
out, props = sys.argv[1], open(sys.argv[2], "rb").read()
extra = dict(a.split("=", 1) for a in sys.argv[3:])
tin = tarfile.open(src); tout = tarfile.open(out + ".tar", "w", format=tarfile.PAX_FORMAT)
rc_template = None
for m in tin.getmembers():
    data = tin.extractfile(m).read() if m.isfile() else None
    if m.name == "etc/build.prop":
        data = data.rstrip(b"\n") + b"\n\n" + props; m.size = len(data)
    if m.name == "etc/init/andarium-background.rc": rc_template = m
    tout.addfile(m, io.BytesIO(data) if data is not None else None)
for name, path in extra.items():
    data = open(path, "rb").read()
    m = tarfile.TarInfo("etc/init/" + name); m.mode = rc_template.mode; m.uid = m.gid = 0; m.mtime = rc_template.mtime
    m.pax_headers = dict(rc_template.pax_headers); m.size = len(data)
    tout.addfile(m, io.BytesIO(data))
tout.close()
subprocess.run(["mkfs.erofs", "--tar=f", "-zzstd", "-T", "1230768000", "--quiet", out, out + ".tar"], check=True)
