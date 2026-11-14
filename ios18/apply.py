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
            (".navigationSubtitle(", ".andariumNavigationSubtitle("),
            (".labelIconToTitleSpacing(", ".andariumLabelSpacing("),
            ("private var glass: Glass {", "private var glass: AndariumGlass {"),
        ):
            updated = updated.replace(old, new)
        if text != updated:
            path.write_text(updated)
            changed += 1
    if changed == 0:
        raise ValueError("No UI call sites changed; upstream layout may have changed")
    shutil.copyfile(Path(__file__).with_name("Compatibility.swift"), shared / "Compatibility.swift")
    replace_required(
        shared / "FileBrowserView.swift",
        "        ToolbarSpacer(.fixed, placement: .topBarTrailing)",
        "        if #available(iOS 26.0, *) {\n"
        "            ToolbarSpacer(.fixed, placement: .topBarTrailing)\n"
        "        }",
    )
    replace_required(
        shared / "FileBrowserBar.swift",
        "    func scrollEdgeEffectHidden() -> some View {\n"
        "        scrollEdgeEffectStyle(.none, for: .horizontal)\n"
        "    }",
        "    @ViewBuilder func scrollEdgeEffectHidden() -> some View {\n"
        "        if #available(iOS 26.0, *) {\n"
        "            scrollEdgeEffectStyle(.none, for: .horizontal)\n"
        "        } else {\n"
        "            self\n"
        "        }\n"
        "    }",
    )
    hosting = shared / "AndariumHostingController.swift"
    replace_required(
        hosting, "private var lockRequested = false",
        "private var lockRequested = false\n"
        "    private var legacyLockedOrientation: UIInterfaceOrientation?",
    )
    replace_required(
        hosting,
        "        UIDevice.current.userInterfaceIdiom == .phone ? .portrait : .all",
        "        if UIDevice.current.userInterfaceIdiom == .phone { return .portrait }\n"
        "        if #available(iOS 26.0, *) { return .all }\n"
        "        guard lockRequested, let orientation = legacyLockedOrientation else { return .all }\n"
        "        switch orientation {\n"
        "        case .portrait: return .portrait\n"
        "        case .portraitUpsideDown: return .portraitUpsideDown\n"
        "        case .landscapeLeft: return .landscapeLeft\n"
        "        case .landscapeRight: return .landscapeRight\n"
        "        default: return .all\n"
        "        }",
    )
    for declaration in (
        "override var prefersInterfaceOrientationLocked:",
        "override var childForInterfaceOrientationLock:",
    ):
        replace_required(hosting, declaration, "@available(iOS 26.0, *)\n    " + declaration)
    replace_required(
        hosting, "let size = scene.effectiveGeometry.coordinateSpace.bounds.size",
        "let size: CGSize\n"
        "            let interfaceLocked: Bool\n"
        "            if #available(iOS 26.0, *) {\n"
        "                size = scene.effectiveGeometry.coordinateSpace.bounds.size\n"
        "                interfaceLocked = scene.effectiveGeometry.isInterfaceOrientationLocked\n"
        "            } else {\n"
        "                size = scene.coordinateSpace.bounds.size\n"
        "                interfaceLocked = lockRequested && legacyLockedOrientation == scene.interfaceOrientation\n"
        "            }",
    )
    replace_required(
        hosting, "interfaceLocked: scene.effectiveGeometry.isInterfaceOrientationLocked)",
        "interfaceLocked: interfaceLocked)",
    )
    replace_required(
        hosting, "                setNeedsUpdateOfPrefersInterfaceOrientationLocked()",
        "                if #available(iOS 26.0, *) {\n"
        "                    setNeedsUpdateOfPrefersInterfaceOrientationLocked()\n"
        "                } else {\n"
        "                    legacyLockedOrientation = lockRequested ? scene.interfaceOrientation : nil\n"
        "                    setNeedsUpdateOfSupportedInterfaceOrientations()\n"
        "                }",
    )
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
