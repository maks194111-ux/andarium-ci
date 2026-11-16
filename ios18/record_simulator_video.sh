#!/bin/bash
# Record the actual Simulator display, including stalls. No frame synthesis.
set -uo pipefail
UDID=$1
OUTPUT=$2
DURATION=$3
case "$DURATION" in ''|*[!0-9]*) echo "Invalid recording duration"; exit 2;; esac
if [ "$DURATION" -lt 1 ] || [ "$DURATION" -gt 300 ]; then
  echo "Recording duration must be between 1 and 300 seconds"; exit 2
fi
xcrun simctl io "$UDID" recordVideo --codec=h264 --force "$OUTPUT" > "${OUTPUT%.mp4}.log" 2>&1 &
recorder=$!
finish() {
  kill -INT "$recorder" 2>/dev/null || true
  for flushing in $(seq 1 15); do
    kill -0 "$recorder" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$recorder" 2>/dev/null; then
    kill -TERM "$recorder" 2>/dev/null || true
    sleep 1
    kill -KILL "$recorder" 2>/dev/null || true
  fi
  wait "$recorder" 2>/dev/null || true
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for second in $(seq 1 "$DURATION"); do
  kill -0 "$recorder" 2>/dev/null || break
  sleep 1
done
finish
trap - EXIT
if [ ! -s "$OUTPUT" ]; then
  echo "The Simulator did not produce a video; see the encoder log."
  exit 1
fi
echo "Original real-time Simulator recording saved; no smoothing or speed changes."
