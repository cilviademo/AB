// 32-bit float WAV writer (RIFF/WAVE, fmt 3). Renders are evidence: float, lossless.
#pragma once
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace abwav {

inline bool write(const std::string& path, const std::vector<std::vector<float>>& channels, int sampleRate) {
    if (channels.empty()) return false;
    const uint16_t nch = (uint16_t) channels.size();
    const uint32_t frames = (uint32_t) channels[0].size();
    const uint32_t dataBytes = frames * nch * 4;
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return false;
    auto u32 = [&](uint32_t v) { fwrite(&v, 4, 1, f); };
    auto u16 = [&](uint16_t v) { fwrite(&v, 2, 1, f); };
    fwrite("RIFF", 1, 4, f); u32(36 + dataBytes); fwrite("WAVE", 1, 4, f);
    fwrite("fmt ", 1, 4, f); u32(16); u16(3); u16(nch); u32((uint32_t) sampleRate); u32((uint32_t) sampleRate * nch * 4); u16(nch * 4); u16(32);
    fwrite("data", 1, 4, f); u32(dataBytes);
    for (uint32_t i = 0; i < frames; ++i)
        for (uint16_t c = 0; c < nch; ++c)
            fwrite(&channels[c][i], 4, 1, f);
    fclose(f);
    return true;
}

} // namespace abwav
