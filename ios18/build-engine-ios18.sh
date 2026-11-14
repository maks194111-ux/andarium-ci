#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Staged attempt at the Andarium device runtime for iOS 18 on the ANGLE path.
# Each stage prints a banner; the first failing stage ends the run.
set -euo pipefail
UPSTREAM=$(cd "$1" && pwd)
WORK=$(cd "$2" && pwd)
ANGLE=$(cd "$3" && pwd)
stage() { echo; echo "===== STAGE: $* ====="; }

stage "network dependency sources"
cd "$UPSTREAM"
bash dependencies/prepare.sh --product ios-network
stage "network dependency build for the iOS device"
bash dependencies/build-ios-network.sh --platform ios
find .build/dependencies -maxdepth 3 | head -40
