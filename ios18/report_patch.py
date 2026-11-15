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
        ) + sessionReport(kernelLines: 60)
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
"""),
])
edit("Andarium/Andarium/Shared/EndView.swift", [
    ("                Text(report)\n", "                Text(model.runReportShort)\n"),
])
print("failure report carries the session record")
