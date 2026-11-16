#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record actual host capabilities without assuming a model or a RAM limit.

Adds no private APIs, device identifiers, serial numbers or external uploads.
The error report and startup console carry the device-family model, screen
rate, physical/process-available memory, CPU counts and GPU capability.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1])
model = root / "Andarium/Andarium/Shared/Model.swift"
text = model.read_text()
marker = "import Observation\n"
if text.count(marker) != 1:
    raise SystemExit("host capabilities: imports not found")
text = text.replace(marker, "import Observation\nimport Darwin\nimport Metal\nimport UIKit\nimport os\n")
marker = " + sessionReport(kernelLines: 60) + consoleReport(lines: 80)"
if text.count(marker) != 1:
    raise SystemExit("host capabilities: apply after report_patch.py")
text = text.replace(marker, marker + ' + "\\n" + HostCapabilities.report()')
text += r'''

/// Public runtime readings, not a table guessing a device's available budget.
@MainActor
enum HostCapabilities {
    private static func machine() -> String {
        var count = 0
        guard sysctlbyname("hw.machine", nil, &count, nil, 0) == 0, count > 0
        else { return "unavailable" }
        var bytes = [CChar](repeating: 0, count: count)
        let result = bytes.withUnsafeMutableBufferPointer {
            sysctlbyname("hw.machine", $0.baseAddress, &count, nil, 0)
        }
        guard result == 0 else { return "unavailable" }
        return bytes.withUnsafeBufferPointer {
            String(cString: $0.baseAddress!)
        }
    }

    static func report() -> String {
        let info = ProcessInfo.processInfo
        let screen = UIScreen.main
        var lines = [
            "Host: \(machine()), \(info.operatingSystemVersionString)",
            "Host CPU: \(info.activeProcessorCount) active / \(info.processorCount) logical",
            "Host RAM: physical \(info.physicalMemory >> 20) MiB, currently available to process \(os_proc_available_memory() >> 20) MiB",
            "Host display: \(Int(screen.nativeBounds.width))x\(Int(screen.nativeBounds.height)), maximum \(screen.maximumFramesPerSecond) Hz (not Android FPS)",
            "Host power: lowPower=\(info.isLowPowerModeEnabled), thermalState=\(info.thermalState.rawValue)"
        ]
        if let gpu = MTLCreateSystemDefaultDevice() {
            lines.append("Host GPU: \(gpu.name), allocated \(gpu.currentAllocatedSize >> 20) MiB, maximum single buffer \(gpu.maxBufferLength >> 20) MiB")
            lines.append("Host GPU families: Apple7=\(gpu.supportsFamily(.apple7)), Apple8=\(gpu.supportsFamily(.apple8)), Apple9=\(gpu.supportsFamily(.apple9))")
        } else {
            lines.append("Host GPU: unavailable")
        }
        return lines.joined(separator: "\n")
    }
}
'''
model.write_text(text)
entry = root / "Andarium/Andarium/Live/AppEntry.swift"
text = entry.read_text()
marker = "        ConsoleCapture.start()\n"
if text.count(marker) != 1:
    raise SystemExit("host capabilities: console startup not found")
entry.write_text(text.replace(marker, marker + "        print(HostCapabilities.report())\n"))
print("host capabilities: actual device/CPU/RAM/display/Metal readings added")
