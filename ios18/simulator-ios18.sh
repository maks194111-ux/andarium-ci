#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Make an "iPhone 11 on iOS 18" Simulator on the CI Mac and print its UDID on
# the last line. The runner ships only the newest iOS runtime, so the iOS 18
# one is downloaded from Apple first.
set -euo pipefail
if ! xcrun simctl list runtimes | grep -q "SimRuntime.iOS-18-"; then
  echo "downloading the iOS 18 Simulator runtime" >&2
  xcodebuild -downloadPlatform iOS -buildVersion "${IOS18_VERSION:-18.6}" >&2 \
    || xcodebuild -downloadPlatform iOS -buildVersion 18.5 >&2
fi
xcrun simctl list runtimes >&2
RUNTIME=$(xcrun simctl list runtimes | grep -o "com.apple.CoreSimulator.SimRuntime.iOS-18-[0-9]*" | sort -V | tail -1)
[ -n "$RUNTIME" ] || { echo "no iOS 18 runtime after the download" >&2; exit 1; }
UDID=$(xcrun simctl create "Andarium iPhone 11" com.apple.CoreSimulator.SimDeviceType.iPhone-11 "$RUNTIME")
xcrun simctl boot "$UDID" >&2
xcrun simctl bootstatus "$UDID" -b >&2
df -h / | tail -1 >&2
echo "$UDID"
