#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure actual drawable presentations and this app's GPU command duration."""
from pathlib import Path
import shutil
import sys

gpu = Path(sys.argv[1]) / "darwin/device/gpu"
shutil.copyfile(Path(__file__).with_name("frame_delivery_metrics.hpp"),
                gpu / "frame_delivery_metrics.hpp")
path = gpu / "metal_presentation.mm"
text = path.read_text()


def replace(old, new):
    global text
    if text.count(old) != 1:
        raise SystemExit(f"presentation metrics: expected one match: {old[:70]!r}")
    text = text.replace(old, new)


replace('#include "metal_presentation.hpp"\n',
        '#include "metal_presentation.hpp"\n#include "frame_delivery_metrics.hpp"\n'
        '#include <sys/resource.h>\n#include <mach/mach.h>\n')
replace("    void draw(MTKView* view, CAMetalLayer* layer) noexcept\n",
        """    static double processCpuSeconds() noexcept
    {
        rusage usage{};
        if (getrusage(RUSAGE_SELF, &usage) != 0)
            return -1;
        return static_cast<double>(usage.ru_utime.tv_sec + usage.ru_stime.tv_sec) +
            static_cast<double>(usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) / 1e6;
    }

    static long long processFootprintMiB() noexcept
    {
        task_vm_info_data_t information{};
        mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
        if (task_info(mach_task_self(), TASK_VM_INFO,
                reinterpret_cast<task_info_t>(&information), &count) != KERN_SUCCESS)
            return -1;
        return static_cast<long long>(information.phys_footprint >> 20);
    }

    FrameDeliveryMetrics deliveryMetrics;
    const bool deliveryMetricsEnabled =
        std::getenv("UML_PRESENT_METRICS") != nullptr;

    void draw(MTKView* view, CAMetalLayer* layer) noexcept
""")
replace("""                [buffer addCompletedHandler:^(id<MTLCommandBuffer>) {
                    state->presentedFrames.fetch_add(
""",
        """                if (deliveryMetricsEnabled) {
                    [drawable addPresentedHandler:^(id<MTLDrawable> shown) {
                        const auto measured = state->deliveryMetrics.presented(
                            shown.presentedTime, contentGeneration, state->processCpuSeconds());
                        if (measured) {
                            const auto& m = *measured;
                            std::fprintf(stderr,
                                "Native display actual: %.2f s, %u distinct content frames, "
                                "%.2f delivered FPS; intervals p50 %.2f p90 %.2f p99 %.2f "
                                "worst %.2f ms; presentation GPU %.3f ms (%u samples); "
                                "process CPU %.2f cores, footprint %lld MiB, "
                                "Metal allocations %llu MiB\\\\n",
                                m.seconds, m.frames, m.fps, m.p50Ms, m.p90Ms,
                                m.p99Ms, m.worstMs, m.gpuAverageMs, m.gpuSamples,
                                m.processCpuCores, state->processFootprintMiB(),
                                static_cast<unsigned long long>(
                                    state->device.currentAllocatedSize >> 20));
                        }
                    }];
                }
                [buffer addCompletedHandler:^(id<MTLCommandBuffer> completed) {
                    if (state->deliveryMetricsEnabled)
                        state->deliveryMetrics.gpuCompleted(
                            completed.GPUStartTime, completed.GPUEndTime);
                    state->presentedFrames.fetch_add(
""")
# The generated Objective-C string needs a C newline escape, not a literal
# backslash followed by n in the process's console.
text = text.replace('MiB\\\\n"', 'MiB\\n"')
path.write_text(text)
print("presentation metrics: actual distinct-content delivery and own GPU time (opt in)")
