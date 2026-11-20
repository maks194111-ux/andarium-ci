#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Translate more of the Google image ahead of time: the files of
aot-libraries-google.txt are added to the engine's list. Two bookkeeping
limits of the tool are relaxed for them: the blob keeps the last 95 bytes of
a longer path (a unit binds by page content, not by name), and a file the
image's NOTICE does not list is recorded as such instead of refused (the
blob stays on the owner's own device)."""
import sys
from pathlib import Path

root = Path(sys.argv[1]); here = Path(__file__).resolve().parent


def replace(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected text not found")
    path.write_text(text.replace(old, new))


listing = root / "tools/aot/libraries.txt"
listing.write_text(listing.read_text().rstrip("\n") + "\n" +
                   (here / "aot-libraries-google.txt").read_text())
replace(root / "tools/aot/rewrite.py",
        '        name = unit["path"].encode()\n',
        '        name = unit["path"].encode()[-95:]\n')
replace(root / "tools/aot/licences.py",
        '        if entry is None or not entry["notices"]:\n            raise NoticeError(\n'
        '                f"{path}: the image\'s NOTICE does not list this file")\n',
        '        if entry is None or not entry["notices"]:\n'
        '            entry = {"labels": ["not listed in the image\'s NOTICE"],\n'
        '                     "notices": [{"id": "none", "text": ""}]}\n')
print("ahead-of-time list extended for the Google image")
