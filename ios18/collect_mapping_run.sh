#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Wait for one existing run; never dispatch a duplicate.
set -euo pipefail
RUN=$1
OUT=$2
PREFIX=${3:-mapping}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=repos/maks194111-ux/andarium-ci
previous=
for attempt in $(seq 1 60); do
  state=$(gh api "$REPO/actions/runs/$RUN" --jq .status)
  if [ "$state" != "$previous" ]; then
    echo "Run $RUN: $state"
    previous=$state
  fi
  if [ "$state" = completed ]; then
    conclusion=$(gh api "$REPO/actions/runs/$RUN" --jq .conclusion)
    echo "Run $RUN: $conclusion"
    artifact=$(gh api "$REPO/actions/runs/$RUN/artifacts" --jq '.artifacts[]|select(.name=="angle-boot-report")|.id')
    if [ -z "$artifact" ]; then
      echo "No boot report. The comparison did not run; no performance conclusion."
      exit 1
    fi
    mkdir -p "$OUT"
    gh api "$REPO/actions/artifacts/$artifact/zip" > "$OUT/report.zip"
    python3 - "$OUT" <<'PY'
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
root = Path(sys.argv[1])
with zipfile.ZipFile(root / "report.zip") as z:
    for entry in z.infolist():
        p = PurePosixPath(entry.filename)
        if p.is_absolute() or ".." in p.parts or stat.S_ISLNK(entry.external_attr >> 16):
            raise SystemExit("Unsafe report archive member")
    z.extractall(root / "report")
PY
    python3 "$HERE/compare_mapping.py" "$OUT/report" --prefix "$PREFIX" > "$OUT/comparison.json"
    cat "$OUT/comparison.json"
    [ "$conclusion" = success ]
    exit
  fi
  sleep 120
done
echo "Run did not finish within two hours. It has not been cancelled."
exit 2
