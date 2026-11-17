#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""On-device performance diagnostics for a person without a Mac.

engine: the runtime tells the presentation metrics when a finger goes down or
        up, so each metrics line carries the time from a touch to the first
        changed frame (presentation_metrics_patch.py prints it).
app:    every session writes the metrics lines (delivered frames per second,
        frame interval percentiles, stalls, GPU time, processor use, memory,
        thermal state, touch response) to the console file, and the session's
        Settings has "Copy performance report", which puts the device's
        description and those lines on the clipboard.  Home gains a 1.25x
        drawing scale between point resolution and Retina.
Nothing here changes how the guest runs; measuring costs one callback a frame.
Usage: diagnostics_patch.py <upstream> engine|app
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
    edit("Kernarium/Runtime/KernariumRuntime.mm", [
        ("""void runtimeSendTouch(
    uint32_t slot,
    uint32_t x,
    uint32_t y,
    int pressed)
{
    std::lock_guard lock(activeInputMutex);
""",
         """// Diagnostics: which contacts are down, to tell a finger going down or up
// from one that moves.
std::array<bool, KERNARIUM_RUNTIME_TOUCH_CONTACTS> diagnosticContactDown {};

void runtimeSendTouch(
    uint32_t slot,
    uint32_t x,
    uint32_t y,
    int pressed)
{
    std::lock_guard lock(activeInputMutex);
    if (slot < diagnosticContactDown.size() &&
        diagnosticContactDown[slot] != (pressed != 0)) {
        diagnosticContactDown[slot] = pressed != 0;
        uml_note_touch_event();
    }
"""),
        # Declared outside the file's unnamed namespaces, where a C function
        # would get internal linkage.
        ("#include \"KernariumRuntime.h\"\n",
         "#include \"KernariumRuntime.h\"\n"
         "// Diagnostics: the display's metrics time a finger going down or up\n"
         "// against the next changed frame (darwin/device/gpu/metal_presentation.mm).\n"
         "extern \"C\" void uml_note_touch_event(void);\n"),
    ])
    print("engine: touches are timed against the next changed frame")
elif part == "app":
    edit("Andarium/Andarium/Shared/AndariumApp.swift", [
        ("        MesaShaderCache.configureBeforeFirstUse()\n",
         "        MesaShaderCache.configureBeforeFirstUse()\n"
         "        // Diagnostics: every session writes its display metrics to the\n"
         "        // console file, for Settings' performance report.\n"
         "        setenv(\"UML_PRESENT_METRICS\", \"1\", 1)\n"
         "        setenv(\"UML_ANGLE_SCANOUT_STATS\", \"1\", 1)\n"),
    ])
    path = root / "Andarium/Andarium/Shared/Model.swift"
    path.write_text(path.read_text() + """
/// The performance report a person copies from the session's Settings: what
/// the device is, and the measurements the running session wrote.
enum PerformanceReport {
    /// The console lines that are measurements.
    private static let marks = ["Native display actual", "ANGLE scanout", "Andarium thermal state"]
    /// The drawing scale of point-resolution mode (`GuestDisplayView`).
    static let scaleKey = "andarium.pointScale125"

    private static func hardware() -> String {
        var size = 0
        sysctlbyname("hw.machine", nil, &size, nil, 0)
        var machine = [CChar](repeating: 0, count: max(size, 1))
        sysctlbyname("hw.machine", &machine, &size, nil, 0)
        return String(cString: machine)
    }

    @MainActor static func text(retina: Bool, guestCores: Int, guestMemoryMiB: Int) -> String {
        let info = ProcessInfo.processInfo
        let screen = UIScreen.main
        let thermal: String = switch info.thermalState {
        case .nominal: "nominal"
        case .fair: "fair"
        case .serious: "serious"
        case .critical: "critical"
        @unknown default: "unknown"
        }
        let mode = retina ? "Retina" : (UserDefaults.standard.bool(forKey: scaleKey) ? "1.25x" : "points")
        var lines = [
            "Andarium performance report",
            "Device \\(hardware()), \\(UIDevice.current.systemName) \\(info.operatingSystemVersionString)",
            "Screen \\(Int(screen.nativeBounds.width))x\\(Int(screen.nativeBounds.height)), up to \\(screen.maximumFramesPerSecond) Hz; drawing mode \\(mode)",
            "Host processors \\(info.activeProcessorCount), memory \\(info.physicalMemory >> 20) MiB; guest \\(guestCores) processors, \\(guestMemoryMiB) MiB",
            "Thermal state now \\(thermal); low power mode \\(info.isLowPowerModeEnabled ? "on" : "off"); uptime \\(Int(info.systemUptime)) s",
            "Each 'Native display actual' line is about five seconds in which the picture changed.",
        ]
        fflush(nil)
        if let data = try? Data(contentsOf: ConsoleCapture.url) {
            let measured = String(decoding: data, as: UTF8.self)
                .split(separator: "\\n")
                .filter { line in marks.contains { line.contains($0) } }
                .suffix(400)
            lines.append("Measurements: \\(measured.count) lines")
            lines.append(contentsOf: measured.map(String.init))
        } else {
            lines.append("No console file: nothing was measured.")
        }
        return lines.joined(separator: "\\n")
    }
}
""")
    edit("Andarium/Andarium/Shared/Settings.swift", [
        ("""            Toggle(isOn: $session.showStats.animation(.snappy)) {
                rowLabel("Show on screen", symbol: "rectangle.topthird.inset.filled")
            }
""",
         """            Toggle(isOn: $session.showStats.animation(.snappy)) {
                rowLabel("Show on screen", symbol: "rectangle.topthird.inset.filled")
            }
            Button {
                UIPasteboard.general.string = PerformanceReport.text(
                    retina: model.retina, guestCores: model.guest?.cores ?? 0,
                    guestMemoryMiB: model.guest?.memoryMiB ?? 0
                )
            } label: {
                rowLabel("Copy performance report", symbol: "doc.on.doc")
            }
"""),
    ])
    edit("Andarium/Andarium/Shared/HomeSections.swift", [
        ("""                .labelsHidden()
            }
        }
        .id("display")
""",
         """                .labelsHidden()
            }
            OptionRow(title: "1.25x when Retina is off", symbol: "rectangle.inset.filled") {
                Toggle("1.25x when Retina is off", isOn: $scale125)
                    .labelsHidden()
            }
        }
        .id("display")
"""),
    ])
    edit("Andarium/Andarium/Shared/HomeSections.swift", [
        ("""struct DisplaySection: View {
    @Environment(AppModel.self) private var model
""",
         """struct DisplaySection: View {
    @Environment(AppModel.self) private var model
    @AppStorage(PerformanceReport.scaleKey) private var scale125 = false
"""),
    ])
    edit("GuestHost/Sources/GuestDisplay.swift", [
        ("        let scale = retinaMode ? screen.nativeScale : 1\n",
         "        // Between points and Retina: the guest draws 1.25 pixels a point\n"
         "        // and the layer scales the picture up to the screen.\n"
         "        let pointScale: CGFloat = UserDefaults.standard.bool(forKey: \"andarium.pointScale125\") ? 1.25 : 1\n"
         "        let scale = retinaMode ? screen.nativeScale : pointScale\n"),
    ])
    print("app: sessions write display metrics; Settings copies the performance report; 1.25x drawing scale")
else:
    raise SystemExit("part must be engine or app")
