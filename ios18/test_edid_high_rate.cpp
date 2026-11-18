// SPDX-License-Identifier: GPL-2.0-or-later
// Decodes the extension the way Linux's drm_displayid.c and drm_edid.c do.
#include "edid_high_rate.hpp"
#include <cassert>
#include <cstdio>
#include <cstring>

struct Mode { unsigned w, h, hz; };

static double decode(const std::uint8_t* edid, unsigned width, unsigned height)
{
    unsigned sum = 0;
    for (int i = 0; i < 128; ++i) sum += edid[i];
    assert(sum % 256 == 0 && edid[126] == 1);
    assert(edid[54] == 0 && edid[55] == 0 && edid[57] == 0x10); // not a timing
    const std::uint8_t* ext = edid + 128;
    sum = 0;
    for (int i = 0; i < 128; ++i) sum += ext[i];
    assert(sum % 256 == 0 && ext[0] == 0x70);
    const std::uint8_t* base = ext + 1; // rev, bytes, prod_id, ext_count
    const int length = 4 + base[1] + 1;
    assert(length <= 127 - 1 && length == 126);
    sum = 0;
    for (int i = 0; i < length; ++i) sum += base[i];
    assert(sum % 256 == 0);
    const std::uint8_t* block = base + 4;
    assert(block[0] == 0x03 && block[2] % 20 == 0 && block[2] / 20 == 1);
    const std::uint8_t* t = block + 3;
    auto le16 = [](const std::uint8_t* p) { return unsigned(p[0] | (p[1] << 8)); };
    const unsigned clock = ((t[0] | (t[1] << 8) | (t[2] << 16)) + 1) * 10; // kHz
    const unsigned hactive = le16(t + 4) + 1, hblank = le16(t + 6) + 1;
    const unsigned hsync = (le16(t + 8) & 0x7fff) + 1, hsw = le16(t + 10) + 1;
    const unsigned vactive = le16(t + 12) + 1, vblank = le16(t + 14) + 1;
    const unsigned vsync = (le16(t + 16) & 0x7fff) + 1, vsw = le16(t + 18) + 1;
    assert(hactive == width && vactive == height && (t[3] & 0x80));
    assert(hsync + hsw <= hblank && vsync + vsw <= vblank);
    // The next block header is zero: the kernel's iterator stops there.
    for (int i = 23; i < 121; ++i) assert(block[i] == 0);
    return clock * 1000.0 / ((hactive + hblank) * double(vactive + vblank));
}

int main()
{
    std::uint8_t edid[1024];
    // Modes a base timing can name stay untouched.
    for (auto [w, h, hz] : {Mode {1668U, 2388U, 120U}, Mode {2048U, 2732U, 60U}, Mode {1179U, 2556U, 120U}}) {
        std::memset(edid, 0x5a, sizeof edid);
        assert(uml::gpu::finishHighRateEdid(edid, w, h, hz) == 128);
        for (unsigned char byte : edid) assert(byte == 0x5a);
    }
    for (auto [w, h, hz] : {Mode {2048U, 2732U, 120U}, Mode {2064U, 2752U, 120U}, Mode {2732U, 2048U, 120U}}) {
        std::memset(edid, 0, sizeof edid);
        edid[24] = 0x06;
        edid[54] = 0xff; edid[55] = 0xff; // a clamped timing
        unsigned sum = 0;
        for (int i = 0; i < 127; ++i) sum += edid[i];
        edid[127] = static_cast<std::uint8_t>(0U - sum);
        assert(uml::gpu::finishHighRateEdid(edid, w, h, hz) == 256);
        assert(edid[24] == 0x04);
        const double rate = decode(edid, w, h);
        std::printf("%ux%u at %u Hz: extension names %.3f Hz\n", w, h, hz, rate);
        assert(rate > hz - 0.01 && rate < hz + 0.01);
    }
    std::puts("EDID high-rate extension: passed");
}
