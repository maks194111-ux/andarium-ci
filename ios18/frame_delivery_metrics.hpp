// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <optional>

namespace uml::gpu {

struct DeliveredWindow {
    unsigned frames{};
    double seconds{}, fps{}, p50Ms{}, p90Ms{}, p99Ms{}, worstMs{};
    double gpuAverageMs{};
    unsigned gpuSamples{};
    double processCpuCores{-1};
};

// Uses drawable presentation timestamps, not screen refresh ticks or GPU
// completion counts. It measures host delivery of distinct guest content,
// not touch latency or an app's internal simulation FPS.
class FrameDeliveryMetrics {
public:
    void gpuCompleted(double start, double end) noexcept
    {
        if (!std::isfinite(start) || !std::isfinite(end) || start <= 0 || end < start)
            return;
        std::lock_guard lock(mutex_);
        gpuTotalMs_ += (end - start) * 1000;
        ++gpuSamples_;
    }

    std::optional<DeliveredWindow> presented(
        double time, std::uint64_t content, double cpuSeconds = -1) noexcept
    {
        std::lock_guard lock(mutex_);
        if (!std::isfinite(time) || time <= lastTime_ || content == 0 ||
            content <= lastContent_)
            return std::nullopt;
        lastContent_ = content;
        if (frames_ == 0) {
            firstTime_ = lastTime_ = time;
            firstCpuSeconds_ = cpuSeconds;
            frames_ = 1;
            return std::nullopt;
        }
        const double gap = (time - lastTime_) * 1000;
        lastTime_ = time;
        worstMs_ = std::max(worstMs_, gap);
        intervals_[intervalCount_ % intervals_.size()] = gap;
        ++intervalCount_;
        ++frames_;
        const double seconds = time - firstTime_;
        if (seconds < 5)
            return std::nullopt;
        const auto count = std::min(intervalCount_, intervals_.size());
        auto sorted = intervals_;
        std::sort(sorted.begin(), sorted.begin() + count);
        const auto percentile = [&](double p) {
            return sorted[std::min(static_cast<std::size_t>(count * p), count - 1)];
        };
        DeliveredWindow result{
            frames_, seconds, (frames_ - 1) / seconds,
            percentile(0.5), percentile(0.9), percentile(0.99), worstMs_,
            gpuSamples_ ? gpuTotalMs_ / gpuSamples_ : 0, gpuSamples_,
            firstCpuSeconds_ >= 0 && cpuSeconds >= firstCpuSeconds_
                ? (cpuSeconds - firstCpuSeconds_) / seconds : -1
        };
        // Keep the boundary sample so the next window counts its intervals
        // exactly once. Distinct content, rather than rate ticks, is counted.
        firstTime_ = time;
        firstCpuSeconds_ = cpuSeconds;
        frames_ = 1;
        intervalCount_ = 0;
        worstMs_ = gpuTotalMs_ = 0;
        gpuSamples_ = 0;
        return result;
    }

private:
    std::mutex mutex_;
    std::array<double, 1024> intervals_{};
    std::size_t intervalCount_{};
    double firstTime_{}, lastTime_{}, worstMs_{}, gpuTotalMs_{};
    double firstCpuSeconds_{-1};
    std::uint64_t lastContent_{};
    unsigned frames_{}, gpuSamples_{};
};

} // namespace uml::gpu
