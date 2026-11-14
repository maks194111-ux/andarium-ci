#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Point the Andarium app at the ANGLE runtime packaged for iOS 18.

Run after apply.py (deployment target and UI compatibility).  The project
embeds ANGLE's two frameworks instead of Mesa's and has no KosmicKrisp; the
start guard asks for a Metal device instead of a Metal 4 one, because the
runtime this app carries draws through ANGLE on Metal.
"""
import re
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


project = root / "Andarium/Andarium.xcodeproj/project.xcproj"
text = project.read_text()
for old, new in (("MesaEGL.xcframework", "libEGL.xcframework"),
                 ("MesaGallium.xcframework", "libGLESv2.xcframework")):
    if text.count(old) != 1:
        raise SystemExit(f"project: expected one {old}")
    text = text.replace(old, new)
line = '        { "path": "../.build/kernarium-xcframeworks/KosmicKrisp.xcframework" },\n'
if text.count(line) != 1:
    raise SystemExit("project: KosmicKrisp reference not found")
text = text.replace(line, "")
phase = re.compile(r'\{\n\s+"kind": "script",\n\s+"name": "Embed KosmicKrisp \(device only\)",\n(?:.*\n)+?\s+\}, \{\n')
if len(phase.findall(text)) != 1:
    raise SystemExit("project: KosmicKrisp embed phase not found")
text = phase.sub("{\n", text)
project.write_text(text)

edit("Andarium/Andarium/Live/AppEntry.swift", [
    ("return MTLCreateSystemDefaultDevice()?.supportsFamily(.metal4) ?? false",
     "return MTLCreateSystemDefaultDevice() != nil"),
])
edit("Andarium/Andarium/Live/GuestLayer.swift", [
    (".containerCornerOffset(SceneCoverage.cornerOffsetEdges(coversScreen: coversScreen), sizeToFit: true)",
     ".andariumCornerOffset(SceneCoverage.cornerOffsetEdges(coversScreen: coversScreen))"),
])
layer = root / "Andarium/Andarium/Live/GuestLayer.swift"
layer.write_text(layer.read_text() + """
// iOS 18 compatibility: the window-control corner offset exists from iOS 26;
// before it there are no overlaid window controls to move away from.
private extension View {
    @ViewBuilder func andariumCornerOffset(_ edges: Edge.Set) -> some View {
        if #available(iOS 26.0, *) {
            containerCornerOffset(edges, sizeToFit: true)
        } else {
            self
        }
    }
}
""")
edit("GuestHost/Sources/GuestDisplay.swift", [
    ("""                self.perform(self.resizeHold.interactiveResizeChanged(
                    scene.effectiveGeometry.isInteractivelyResizing
                ))""",
     """                var resizing = false
                if #available(iOS 26.0, *) {
                    resizing = scene.effectiveGeometry.isInteractivelyResizing
                }
                self.perform(self.resizeHold.interactiveResizeChanged(resizing))"""),
])
edit("GuestHost/Sources/SceneCoverage.swift", [
    ("""        covers(
            sceneSize: scene.effectiveGeometry.coordinateSpace.bounds.size,
            screenSize: scene.screen.bounds.size
        )""",
     """        let sceneSize: CGSize
        if #available(iOS 26.0, *) {
            sceneSize = scene.effectiveGeometry.coordinateSpace.bounds.size
        } else {
            sceneSize = scene.coordinateSpace.bounds.size
        }
        return covers(sceneSize: sceneSize, screenSize: scene.screen.bounds.size)"""),
])
print("app project uses the ANGLE runtime; start guard asks for a Metal device")
