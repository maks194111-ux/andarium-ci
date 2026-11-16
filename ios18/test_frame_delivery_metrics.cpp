// SPDX-License-Identifier: GPL-2.0-or-later
#include "frame_delivery_metrics.hpp"
#include <cassert>
#include <cmath>
#include <limits>

using uml::gpu::DeliveredWindow;
using uml::gpu::FrameDeliveryMetrics;

void rate(double hz)
{
    FrameDeliveryMetrics metrics;
    std::optional<DeliveredWindow> result;
    for (unsigned i = 0; i < hz * 6; ++i) {
        metrics.gpuCompleted(1, 1.002);
        auto next = metrics.presented(100 + i / hz, i + 1);
        // Presenting the same Android content again must not inflate FPS.
        assert(!metrics.presented(100 + (i + 0.1) / hz, i + 1));
        if (next)
            result = next;
    }
    assert(result);
    assert(std::abs(result->fps - hz) < 0.01);
    assert(std::abs(result->p90Ms - 1000 / hz) < 0.01);
    assert(std::abs(result->gpuAverageMs - 2) < 0.01);
}

int main()
{
    rate(60);
    rate(120);
    FrameDeliveryMetrics metrics;
    assert(!metrics.presented(std::numeric_limits<double>::quiet_NaN(), 1));
    assert(!metrics.presented(0, 1));
    assert(!metrics.presented(1, 0));
    assert(!metrics.presented(10, 1));
    assert(!metrics.presented(9, 2));
    auto slow = metrics.presented(16, 3);
    assert(slow && slow->fps < 1 && slow->worstMs == 6000);
    // Geometry-only redraw of an old content generation is not a new frame.
    assert(!metrics.presented(17, 2));
}
