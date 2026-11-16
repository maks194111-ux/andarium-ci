#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in iOS presentation experiment, independent of Android's EDID rate.

FIX9 dispatches one main-queue draw for each available guest frame. Here an
idle-paused CADisplayLink consumes the newest pending frame at a display tick,
with an adaptive 30..screen-maximum range, capped at 120. No duplicate guest
frames are fabricated. UML_DISPLAY_PACING=1 selects it; otherwise FIX9's
redraw scheduling is unchanged. Not a claim of 120 rendered Android FPS.
"""
from pathlib import Path
import sys

path = Path(sys.argv[1]) / "darwin/device/gpu/native_display_ios.mm"
text = path.read_text()


def replace(old, new):
    global text
    if text.count(old) != 1:
        raise SystemExit(f"display pacing: expected one match: {old[:80]!r}")
    text = text.replace(old, new)


replace("#include <atomic>\n", "#include <atomic>\n#include <algorithm>\n#include <cstdlib>\n#include <cstring>\n")
replace("    id<MTKViewDelegate> delegate;\n",
        "    id<MTKViewDelegate> delegate;\n    CADisplayLink* displayLink;\n")
replace("@interface UmlIOSMetalViewDelegate : NSObject <MTKViewDelegate>\n",
        "@interface UmlIOSMetalViewDelegate : NSObject <MTKViewDelegate>\n"
        "- (void)displayTick:(CADisplayLink*)link;\n")
replace("- (void)drawInMTKView:(MTKView*)view\n",
        """- (void)displayTick:(CADisplayLink*)link
{
    auto state = _state.lock();
    if (!state || !state->running.load(std::memory_order_acquire)) {
        [link invalidate];
        return;
    }
    if (state->redrawScheduled.exchange(false, std::memory_order_acq_rel)) {
        MTKView* view = state->view;
        if (view != nil)
            [view draw];
    } else {
        // A static Android screen needs no repeated host redraws.
        link.paused = YES;
    }
}

- (void)drawInMTKView:(MTKView*)view
""")
replace("        metalView.delegate = viewDelegate;\n",
        """        metalView.delegate = viewDelegate;
        const char* pacing = std::getenv("UML_DISPLAY_PACING");
        if (pacing != nullptr && std::strcmp(pacing, "1") == 0) {
            UIScreen* screen = metalView.window.screen ?: UIScreen.mainScreen;
            const float maximum = std::clamp(
                static_cast<float>(screen.maximumFramesPerSecond), 30.0F, 120.0F);
            CADisplayLink* link = [CADisplayLink
                displayLinkWithTarget:viewDelegate selector:@selector(displayTick:)];
            link.preferredFrameRateRange = CAFrameRateRangeMake(
                std::min(30.0F, maximum), maximum, maximum);
            link.paused = YES;
            [link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
            state->displayLink = link;
        }
""")
replace("""        state->redrawScheduled.store(false, std::memory_order_release);
        if (!state->running.load(std::memory_order_acquire))
            return;
        MTKView* nativeView = state->view;
""",
        """        if (!state->running.load(std::memory_order_acquire)) {
            state->redrawScheduled.store(false, std::memory_order_release);
            return;
        }
        if (state->displayLink != nil) {
            state->displayLink.paused = NO;
            return;
        }
        state->redrawScheduled.store(false, std::memory_order_release);
        MTKView* nativeView = state->view;
""")
replace("""        if (nativeView.delegate == state->delegate)
            nativeView.delegate = nil;
""",
        """        [state->displayLink invalidate];
        state->displayLink = nil;
        if (nativeView.delegate == state->delegate)
            nativeView.delegate = nil;
""")
path.write_text(text)
print("iOS display pacing installed (opt in: UML_DISPLAY_PACING=1; idle-paused, <=120 Hz)")
