// SPDX-License-Identifier: GPL-2.0-or-later
import SwiftUI

/// Retain the new appearance on supported OS versions and use system
/// materials on iOS 18. This does not change guest graphics capabilities.
struct AndariumGlass {
    var tintColor: Color?
    var isInteractive = false

    static let regular = AndariumGlass()

    func tint(_ color: Color) -> Self {
        var copy = self
        copy.tintColor = color
        return copy
    }

    func interactive() -> Self {
        var copy = self
        copy.isInteractive = true
        return copy
    }

    @available(iOS 26.0, *)
    var native: Glass {
        var value = Glass.regular
        if let tintColor { value = value.tint(tintColor) }
        if isInteractive { value = value.interactive() }
        return value
    }
}

extension View {
    @ViewBuilder
    func andariumGlassEffect<S: Shape>(_ glass: AndariumGlass, in shape: S) -> some View {
        if #available(iOS 26.0, *) {
            self.glassEffect(glass.native, in: shape)
        } else {
            self
                .background(.ultraThinMaterial, in: shape)
                .background(glass.tintColor ?? .clear, in: shape)
        }
    }

    @ViewBuilder
    func andariumGlassButtonStyle(prominent: Bool = false) -> some View {
        if #available(iOS 26.0, *) {
            if prominent {
                self.buttonStyle(.glassProminent)
            } else {
                self.buttonStyle(.glass)
            }
        } else {
            if prominent {
                self.buttonStyle(.borderedProminent)
            } else {
                self.buttonStyle(.bordered)
            }
        }
    }

    @ViewBuilder
    func andariumSafeAreaBar<Bar: View>(
        edge: VerticalEdge, @ViewBuilder content: () -> Bar
    ) -> some View {
        if #available(iOS 26.0, *) {
            self.safeAreaBar(edge: edge, content: content)
        } else {
            self.safeAreaInset(edge: edge, spacing: 0, content: content)
        }
    }
}

struct AndariumGlassContainer<Content: View>: View {
    let spacing: CGFloat
    let content: Content

    init(spacing: CGFloat, @ViewBuilder content: () -> Content) {
        self.spacing = spacing
        self.content = content()
    }

    @ViewBuilder
    var body: some View {
        if #available(iOS 26.0, *) {
            GlassEffectContainer(spacing: spacing) { content }
        } else {
            content
        }
    }
}
