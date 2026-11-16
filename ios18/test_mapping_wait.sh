#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail
ROOT=$1
HERE=$(cd "$(dirname "$0")" && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/darwin/memory/mmu"
cp "$ROOT/darwin/memory/mmu/word_shared_mutex.hpp" "$TMP/darwin/memory/mmu/"
python3 "$HERE/mapping_wait_patch.py" "$TMP"
INCLUDES=$(find "$ROOT/tests" -name wait_until.hpp -exec dirname '{}' \; | head -1)
"${CXX:-c++}" -std=c++20 -O2 -pthread \
  -I"$TMP/darwin/memory/mmu" -I"$INCLUDES" \
  "$ROOT/tests/unit/memory/word_shared_mutex_tests.cpp" -o "$TMP/test"
for mode in 0 1; do
  for round in 1 2 3; do
    echo "mapping lock correctness mode=$mode round=$round"
    UML_MAPPING_WAIT=$mode "$TMP/test"
  done
done
