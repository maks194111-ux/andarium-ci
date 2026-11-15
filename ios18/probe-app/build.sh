#!/bin/bash
# SPDX-License-Identifier: MIT
# Builds the debuggable probe application with the SDK already on the runner.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$1; mkdir -p "$OUT"; WORK=$(mktemp -d)
TOOLS=$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -1)
PLATFORM=$(ls -d "$ANDROID_HOME"/platforms/android-* | sort -V | tail -1)/android.jar
echo "build tools: $TOOLS; platform: $PLATFORM"
"$TOOLS/aapt2" link -o "$WORK/base.apk" --manifest "$HERE/AndroidManifest.xml" -I "$PLATFORM"
mkdir -p "$WORK/classes" "$WORK/dex"
javac -source 8 -target 8 -nowarn -cp "$PLATFORM" -d "$WORK/classes" $(find "$HERE/src" -name '*.java')
"$TOOLS/d8" --lib "$PLATFORM" --min-api 26 --output "$WORK/dex" $(find "$WORK/classes" -name '*.class')
(cd "$WORK/dex" && zip -q "$WORK/base.apk" classes.dex)
"$TOOLS/zipalign" -f 4 "$WORK/base.apk" "$WORK/aligned.apk"
keytool -genkeypair -keystore "$WORK/key.jks" -storepass android -keypass android -alias probe \
  -keyalg RSA -keysize 2048 -validity 3650 -dname "CN=Andarium probe" >/dev/null 2>&1
"$TOOLS/apksigner" sign --ks "$WORK/key.jks" --ks-pass pass:android --key-pass pass:android \
  --out "$OUT/probe.apk" "$WORK/aligned.apk"
"$TOOLS/aapt2" dump badging "$OUT/probe.apk" | grep -E "package|debuggable"
ls -la "$OUT/probe.apk"
NDK=${ANDROID_NDK_LATEST_HOME:-$ANDROID_NDK_HOME}
"$NDK"/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android30-clang -O2 -o "$OUT/micro" "$HERE/native/micro.c"
ls -la "$OUT/micro"
