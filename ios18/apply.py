"""Apply the UI/model iOS 18 compatibility layer to a pinned upstream tree.

This is NOT an emulator/graphics port. The Metal 4 startup guard is retained.
"""
# SPDX-License-Identifier: GPL-2.0-or-later
import argparse
from pathlib import Path
import shutil


def replace_required(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise ValueError(f"Expected upstream text not found in {path.name}: {old}")
    path.write_text(text.replace(old, new))


def apply(root: Path) -> None:
    for relative in ("Andarium/AndariumCore/Package.swift", "GuestHost/Core/Package.swift"):
        path = root / relative
        replace_required(path, '.iOS("27.0")', '.iOS("18.0")')
        replace_required(path, '.macOS("27.0")', '.macOS("15.0")')
    replace_required(
        root / "Andarium/Andarium.xcodeproj/project.xcproj",
        '"IPHONEOS_DEPLOYMENT_TARGET": "27.0"',
        '"IPHONEOS_DEPLOYMENT_TARGET": "18.0"',
    )
    shared = root / "Andarium/Andarium/Shared"
    changed = 0
    for path in sorted(shared.glob("*.swift")):
        text = path.read_text()
        updated = text
        for old, new in (
            (".glassEffect(", ".andariumGlassEffect("),
            ("GlassEffectContainer(", "AndariumGlassContainer("),
            (".buttonStyle(.glassProminent)", ".andariumGlassButtonStyle(prominent: true)"),
            (".buttonStyle(.glass)", ".andariumGlassButtonStyle()"),
            (".safeAreaBar(", ".andariumSafeAreaBar("),
            ("private var glass: Glass {", "private var glass: AndariumGlass {"),
        ):
            updated = updated.replace(old, new)
        if text != updated:
            path.write_text(updated)
            changed += 1
    if changed == 0:
        raise ValueError("No UI call sites changed; upstream layout may have changed")
    shutil.copyfile(Path(__file__).with_name("Compatibility.swift"), shared / "Compatibility.swift")
    # Do not pretend that iOS 18 has Metal 4. Gate the enum reference but keep
    # the original device capability restriction until a backend is ported.
    replace_required(
        root / "Andarium/Andarium/Live/AppEntry.swift",
        "return MTLCreateSystemDefaultDevice()?.supportsFamily(.metal4) ?? false",
        "if #available(iOS 26.0, *) {\n"
        "            return MTLCreateSystemDefaultDevice()?.supportsFamily(.metal4) ?? false\n"
        "        }\n"
        "        return false",
    )
    print(f"Applied UI compatibility to {changed} files; guest graphics guard retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    apply(parser.parse_args().upstream)
