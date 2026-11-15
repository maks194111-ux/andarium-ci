#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The failure screen's report says why the guest ended.

Upstream's screen shows only the run's number.  The runtime already records
how the session ended, with its memory figures and the guest kernel's last
output (darwin/runtime/session_record.hpp), but that record leaves the device
only inside an Android bug report, which a guest that has stopped cannot
make.  With this patch "Copy report" carries the record too; the screen shows
its first lines.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])


def edit(relative: str, changes) -> None:
    path = root / relative
    text = path.read_text()
    for old, new in changes:
        if text.count(old) != 1:
            raise SystemExit(f"{relative}: expected one match for {old[:60]!r}, found {text.count(old)}")
        text = text.replace(old, new)
    path.write_text(text)


edit("Andarium/Andarium/Shared/Model.swift", [
    ("""    var runReport: String {
        runEnd.report(
            appVersion: system.appVersion, system: system, guest: guest, uptimeSeconds: runUptimeSeconds
        )
    }
""",
     """    var runReport: String {
        runEnd.report(
            appVersion: system.appVersion, system: system, guest: guest, uptimeSeconds: runUptimeSeconds
        ) + sessionReport(kernelLines: 60) + consoleReport(lines: 80)
    }

    /// The report's lines the screen has room for.
    var runReportShort: String {
        runEnd.report(
            appVersion: system.appVersion, system: system, guest: guest, uptimeSeconds: runUptimeSeconds
        ) + sessionReport(kernelLines: 0)
    }

    /// How the runtime recorded the session's end: its word for the end, the
    /// memory figures of the last checkpoint and the guest kernel's last
    /// lines. Empty when there is no record.
    private func sessionReport(kernelLines: Int) -> String {
        guard let directory = diagnosticsDirectory,
              let data = try? Data(contentsOf: directory.appendingPathComponent(BugReportAttachments.sessionRecord)),
              let record = SessionRecord(text: String(decoding: data, as: UTF8.self))
        else { return "" }
        var lines = ["Session: \\(record.end) status \\(record.status)" + (record.message.map { ": \\($0)" } ?? "")]
        if let memory = record.memory {
            var line = "Memory: \\(memory.footprintBytes >> 20) MiB, peak \\(memory.peakBytes >> 20) MiB"
            if let available = memory.availableBytes { line += ", left \\(available >> 20) MiB" }
            lines.append(line)
        }
        if kernelLines > 0 {
            if let terms = record.terms { lines.append("Terms: \\(terms)") }
            if let peak = record.peakTerms { lines.append("Peak terms: \\(peak)") }
            if let output = record.kernelOutput {
                lines.append("Kernel:")
                lines.append(contentsOf: output.split(separator: "\\n").suffix(kernelLines).map(String.init))
            }
        }
        return "\\n" + DiagnosticRedaction.redact(lines.joined(separator: "\\n"), containers: diagnosticsContainers)
    }

    /// The last lines the process wrote to its console (`ConsoleCapture`).
    private func consoleReport(lines count: Int) -> String {
        let tail = ConsoleCapture.tail(lines: count)
        guard !tail.isEmpty else { return "" }
        return "\\nConsole:\\n" + DiagnosticRedaction.redact(tail, containers: diagnosticsContainers)
    }
"""),
])
# What the process writes to its console (the runtime's own messages and the
# guest kernel's) is kept in a file, because nothing else on a phone shows it.
path = root / "Andarium/Andarium/Shared/Model.swift"
path.write_text(path.read_text() + """
/// Keeps what the process writes to its console in a file, so the failure
/// screen's report can carry the last lines: a start that fails before the
/// guest runs leaves no session record, only those lines.
enum ConsoleCapture {
    static var url: URL {
        let directory = (try? FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true
        )) ?? FileManager.default.temporaryDirectory
        return directory.appendingPathComponent("console.log")
    }

    /// Sends the process's output to the file, emptied at each launch. A
    /// launch from a terminal keeps its terminal.
    static func start() {
        guard isatty(STDERR_FILENO) == 0 else { return }
        let descriptor = open(url.path, O_WRONLY | O_CREAT | O_TRUNC | O_APPEND, 0o644)
        guard descriptor >= 0 else { return }
        dup2(descriptor, STDOUT_FILENO)
        dup2(descriptor, STDERR_FILENO)
        close(descriptor)
    }

    /// The file's last `count` lines, from its last 48 KiB.
    static func tail(lines count: Int) -> String {
        fflush(nil)
        guard let handle = try? FileHandle(forReadingFrom: url) else { return "" }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        try? handle.seek(toOffset: size > 48 << 10 ? size - (48 << 10) : 0)
        let data = (try? handle.readToEnd()) ?? Data()
        return String(decoding: data, as: UTF8.self)
            .split(separator: "\\n").suffix(count).joined(separator: "\\n")
    }
}
""")
edit("Andarium/Andarium/Live/AppEntry.swift", [
    ("""        let info = ProcessInfo.processInfo
        let overrides = LaunchOverrides(
            environment: info.environment,
""",
     """        let info = ProcessInfo.processInfo
        ConsoleCapture.start()
        let overrides = LaunchOverrides(
            environment: info.environment,
"""),
])
edit("Andarium/Andarium/Shared/EndView.swift", [
    ("                Text(report)\n", "                Text(model.runReportShort)\n"),
])
print("failure report carries the session record")
