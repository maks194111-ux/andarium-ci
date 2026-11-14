#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Let the guest display run at the host screen's refresh rate (experiment).

Upstream fixes the guest at 60 Hz: the EDID the GPU device hands the guest
names a 60 Hz mode (the guest kernel paces its vblank timer from it), and the
app does not opt in to rates above 60 Hz on iPhone.  With this patch:
  engine: the EDID's rate comes from UML_GUEST_REFRESH_HZ (30..120, default 60);
  app:    the app sets it from the screen's maximum rate and declares
          CADisableMinimumFrameDurationOnPhone.
Usage: refresh_patch.py <upstream> engine|app
Whether a phone sustains the higher rate is not established by this patch.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
part = sys.argv[2]


def edit(relative: str, changes) -> None:
    path = root / relative
    text = path.read_text()
    for old, new in changes:
        if text.count(old) != 1:
            raise SystemExit(f"{relative}: expected one match for {old[:60]!r}, found {text.count(old)}")
        text = text.replace(old, new)
    path.write_text(text)


if part == "engine":
    edit("darwin/device/gpu/virtio_gpu_device.cpp", [
        ("#include <cstdio>\n", "#include <cstdio>\n#include <cstdlib>\n"),
        ("std::array<std::uint8_t, protocol::baseEdidSize> makeEdid(\n",
         "// Experiment: the refresh rate of the mode the guest is offered. The host\n"
         "// application names its screen's rate; without it the rate is upstream's.\n"
         "std::uint64_t guestRefreshHertz() noexcept\n"
         "{\n"
         "    const char* text = std::getenv(\"UML_GUEST_REFRESH_HZ\");\n"
         "    if (text == nullptr)\n"
         "        return 60U;\n"
         "    const long value = std::strtol(text, nullptr, 10);\n"
         "    if (value < 30 || value > 120)\n"
         "        return 60U;\n"
         "    return static_cast<std::uint64_t>(value);\n"
         "}\n\n"
         "std::array<std::uint8_t, protocol::baseEdidSize> makeEdid(\n"),
        ("             (static_cast<std::uint64_t>(height) + verticalBlank) * 60U +\n",
         "             (static_cast<std::uint64_t>(height) + verticalBlank) *\n"
         "                 guestRefreshHertz() +\n"),
    ])
    print("engine: guest refresh rate follows UML_GUEST_REFRESH_HZ")
elif part == "app":
    edit("Andarium/Config/Info.plist", [
        ("<key>UIRequiredDeviceCapabilities</key>",
         "<key>CADisableMinimumFrameDurationOnPhone</key>\n<true/>\n<key>UIRequiredDeviceCapabilities</key>"),
    ])
    edit("Andarium/Andarium/Shared/AndariumApp.swift", [
        ("        MesaShaderCache.configureBeforeFirstUse()\n",
         "        MesaShaderCache.configureBeforeFirstUse()\n"
         "        // Experiment: the guest display runs at this screen's rate. The GPU\n"
         "        // device reads it when it describes the display to the guest.\n"
         "        setenv(\"UML_GUEST_REFRESH_HZ\", String(UIScreen.main.maximumFramesPerSecond), 1)\n"),
    ])
    print("app: opts in to the screen's full refresh rate")
else:
    raise SystemExit("part must be engine or app")
