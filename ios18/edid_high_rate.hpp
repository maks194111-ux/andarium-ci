// SPDX-License-Identifier: GPL-2.0-or-later
// A base EDID detailed timing holds its pixel clock in 16 bits of 10 kHz, at
// most 655.35 MHz. A 2048x2732 display at 120 Hz needs about 846 MHz, so the
// clamped clock gave the guest a mode near 93 Hz, which no 120 Hz screen shows
// evenly. Such a mode is described in a DisplayID extension block (type I
// detailed timing, 24-bit clock) and the base block carries no timing.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>

namespace uml::gpu {

// `edid` holds a finished 128-byte base block and has room for 256 bytes.
// Returns the EDID size to report: 128 when the base timing already names
// the mode, 256 when the extension block was written.
inline std::uint32_t finishHighRateEdid(
    std::uint8_t* edid,
    std::uint32_t width,
    std::uint32_t height,
    std::uint64_t hertz) noexcept
{
    const auto horizontalBlank = std::min<std::uint32_t>(
        4095U, std::max<std::uint32_t>(160U, width / 5U));
    const auto verticalBlank = std::min<std::uint32_t>(
        4095U, std::max<std::uint32_t>(30U, height / 20U));
    const std::uint64_t clock =
        ((static_cast<std::uint64_t>(width) + horizontalBlank) *
             (static_cast<std::uint64_t>(height) + verticalBlank) * hertz +
            5000U) /
        10000U;
    if (clock <= 65535U || clock > 0x1000000U)
        return 128U;
    const auto horizontalSync = std::min<std::uint32_t>(
        1023U, std::max<std::uint32_t>(8U, horizontalBlank / 3U));

    // Base block: a dummy descriptor in place of the timing, no "first
    // timing is preferred" claim, one extension block.
    std::fill_n(edid + 54U, 18U, std::uint8_t {0});
    edid[54U + 3U] = 0x10;
    edid[24] = static_cast<std::uint8_t>(edid[24] & ~0x02U);
    edid[126] = 1;
    unsigned sum = 0;
    for (std::size_t index = 0; index < 127U; ++index)
        sum += edid[index];
    edid[127] = static_cast<std::uint8_t>(0U - sum);

    std::uint8_t* block = edid + 128U;
    std::fill_n(block, 128U, std::uint8_t {0});
    block[0] = 0x70; // EDID extension tag: DisplayID.
    block[1] = 0x12; // DisplayID 1.2.
    block[2] = 121;  // Section payload fills the block; zeros after the data.
    block[3] = 0;
    block[4] = 0;
    block[5] = 0x03; // Type I detailed timing data block.
    block[6] = 0;
    block[7] = 20;
    std::uint8_t* timing = block + 8U;
    const auto put16 = [](std::uint8_t* at, std::uint32_t value) {
        at[0] = static_cast<std::uint8_t>(value);
        at[1] = static_cast<std::uint8_t>(value >> 8U);
    };
    const auto stored = static_cast<std::uint32_t>(clock - 1U);
    timing[0] = static_cast<std::uint8_t>(stored);
    timing[1] = static_cast<std::uint8_t>(stored >> 8U);
    timing[2] = static_cast<std::uint8_t>(stored >> 16U);
    timing[3] = 0x80; // Preferred timing.
    put16(timing + 4U, width - 1U);
    put16(timing + 6U, horizontalBlank - 1U);
    put16(timing + 8U, (horizontalSync - 1U) | 0x8000U);
    put16(timing + 10U, horizontalSync - 1U);
    put16(timing + 12U, height - 1U);
    put16(timing + 14U, verticalBlank - 1U);
    put16(timing + 16U, (3U - 1U) | 0x8000U);
    put16(timing + 18U, 5U - 1U);
    sum = 0;
    for (std::size_t index = 1; index < 126U; ++index)
        sum += block[index];
    block[126] = static_cast<std::uint8_t>(0U - sum); // DisplayID checksum.
    sum = 0;
    for (std::size_t index = 0; index < 127U; ++index)
        sum += block[index];
    block[127] = static_cast<std::uint8_t>(0U - sum);
    return 256U;
}

} // namespace uml::gpu
