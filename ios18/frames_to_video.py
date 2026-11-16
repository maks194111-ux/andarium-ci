#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Turn a frame record (frame_record_patch.py) into a video in real time.

Every output picture is the last recorded frame that had arrived by that
instant.  Nothing is interpolated, sped up or dropped: a stall in the record
is a still picture of the same length in the video.

Usage: frames_to_video.py <record> <output.mp4> <timings.csv> [events.txt]

The optional events file has lines "<monotonic nanoseconds> <label>"; the
statistics are then also given per labelled part.
"""
import struct
import subprocess
import sys

import lz4.block

HEADER = struct.Struct("<QIIII")
RATE = 60


def frames(path):
    with open(path, "rb") as source:
        while True:
            raw = source.read(HEADER.size)
            if len(raw) < HEADER.size:
                return
            nanos, width, height, row_bytes, packed = HEADER.unpack(raw)
            size = row_bytes * height
            body = source.read(packed or size)
            if len(body) < (packed or size):
                return
            if packed:
                body = lz4.block.decompress(body, uncompressed_size=size)
            if row_bytes != width * 4:
                body = b"".join(body[r * row_bytes:r * row_bytes + width * 4] for r in range(height))
            yield nanos, width, height, body


def describe(label, times):
    if len(times) < 2:
        print(f"{label}: {len(times)} frame(s)")
        return
    gaps = sorted((b - a) / 1e6 for a, b in zip(times, times[1:]))
    span = (times[-1] - times[0]) / 1e9
    middle = gaps[len(gaps) // 2]
    high = gaps[min(len(gaps) - 1, int(len(gaps) * 0.95))]
    print(f"{label}: {len(times)} frames in {span:.1f} s = {(len(times) - 1) / span:.1f} per second; "
          f"gap median {middle:.1f} ms, 95% {high:.1f} ms, longest {gaps[-1]:.0f} ms; "
          f"gaps over 100 ms: {sum(1 for g in gaps if g > 100)}")


def main():
    record, output, timings = sys.argv[1:4]
    encoder = None
    times = []
    shown = 0
    previous = None
    start = None
    size = None
    for nanos, width, height, body in frames(record):
        if size is None:
            size = (width, height)
            start = nanos
            encoder = subprocess.Popen(
                ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgra",
                 "-s", f"{width}x{height}", "-r", str(RATE), "-i", "-",
                 "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", output],
                stdin=subprocess.PIPE)
        if (width, height) != size:
            print(f"frame of {width}x{height} skipped: the video is {size[0]}x{size[1]}")
            continue
        times.append(nanos)
        # Pictures up to this frame's arrival still show the previous frame.
        due = int((nanos - start) * RATE / 1e9)
        while previous is not None and shown < due:
            encoder.stdin.write(previous)
            shown += 1
        previous = body
    if encoder is None:
        raise SystemExit("the record holds no frame")
    encoder.stdin.write(previous)
    shown += 1
    encoder.stdin.close()
    if encoder.wait() != 0:
        raise SystemExit("ffmpeg failed")
    with open(timings, "w") as out:
        out.write("frame,seconds\n")
        for index, nanos in enumerate(times):
            out.write(f"{index},{(nanos - start) / 1e9:.6f}\n")
    print(f"video: {size[0]}x{size[1]}, {shown} pictures at {RATE} per second = {shown / RATE:.1f} s, "
          f"from {len(times)} recorded frames; real time, no interpolation")
    describe("whole recording", times)
    if len(sys.argv) > 4:
        marks = []
        for line in open(sys.argv[4]):
            stamp, _, label = line.strip().partition(" ")
            if stamp.isdigit():
                marks.append((int(stamp), label))
        for (begin, label), (end, _) in zip(marks, marks[1:]):
            print(f"  at {(begin - start) / 1e9:6.1f} s  ", end="")
            describe(label, [t for t in times if begin <= t < end])


main()
