// Deterministic probe signals (SPEC §11), mirroring reference/…/ProbeSignals.h so the
// Python behaviour stage (engine/ab_engine/behavior/probes.py) generates bit-identical input.
#pragma once
#include <cmath>
#include <cstdint>
#include <string>
#include <vector>

namespace abprobe {

constexpr double kPi = 3.14159265358979323846264338327950288;

struct WhiteNoise { // xorshift32, seed 0x12345678 as in the reference corpus
    uint32_t state;
    explicit WhiteNoise(uint32_t seed = 0x12345678u) : state(seed ? seed : 1u) {}
    float next() { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return (float(state) / float(0xffffffffu)) * 2.0f - 1.0f; }
};

inline std::vector<float> silence(size_t n) { return std::vector<float>(n, 0.0f); }
inline std::vector<float> impulse(size_t n, float amp = 1.0f) { std::vector<float> x(n, 0.0f); if (n) x[0] = amp; return x; }
inline std::vector<float> dc(size_t n, float level = 0.5f) { return std::vector<float>(n, level); }
inline std::vector<float> amplitudeRamp(size_t n, float lo = -4.0f, float hi = 4.0f) { std::vector<float> x(n); for (size_t i = 0; i < n; ++i) x[i] = n > 1 ? lo + (hi - lo) * (float(i) / float(n - 1)) : lo; return x; }
inline std::vector<float> sine(size_t n, double sr, double hz, float amp = 0.5f) { std::vector<float> x(n); for (size_t i = 0; i < n; ++i) x[i] = amp * (float) std::sin(2 * kPi * hz * (double) i / sr); return x; }
inline std::vector<float> sineAmpSweep(size_t n, double sr, double hz, float lo = 0.001f, float hi = 2.0f) { std::vector<float> x(n); for (size_t i = 0; i < n; ++i) { double t = n > 1 ? double(i) / double(n - 1) : 0.0; float amp = lo * (float) std::pow(hi / lo, t); x[i] = amp * (float) std::sin(2 * kPi * hz * (double) i / sr); } return x; }
inline std::vector<float> logSweep(size_t n, double sr, double f0 = 20.0, double f1 = 20000.0, float amp = 0.5f) { std::vector<float> x(n); double T = n / sr, K = T / std::log(f1 / f0), L = 2 * kPi * f0 * K; for (size_t i = 0; i < n; ++i) { double t = i / sr; x[i] = amp * (float) std::sin(L * (std::exp(t / K) - 1)); } return x; }
inline std::vector<float> whiteNoise(size_t n, float amp = 0.25f) { WhiteNoise r; std::vector<float> x(n); for (auto& v : x) v = amp * r.next(); return x; }
inline std::vector<float> pinkNoise(size_t n, float amp = 0.25f) { // Paul Kellet's economy filter over the same white source
    WhiteNoise r; std::vector<float> x(n); float b0 = 0, b1 = 0, b2 = 0;
    for (auto& v : x) { float w = r.next(); b0 = 0.99765f * b0 + w * 0.0990460f; b1 = 0.96300f * b1 + w * 0.2965164f; b2 = 0.57000f * b2 + w * 1.0526913f; v = amp * 0.25f * (b0 + b1 + b2 + w * 0.1848f); }
    return x;
}
inline std::vector<float> twoTone(size_t n, double sr, double f1 = 19000.0, double f2 = 20000.0, float amp = 0.25f) { std::vector<float> x(n); for (size_t i = 0; i < n; ++i) x[i] = amp * (float) (std::sin(2 * kPi * f1 * i / sr) + std::sin(2 * kPi * f2 * i / sr)); return x; }

/** Named probe → signal. Unknown names return an empty vector. */
inline std::vector<float> make(const std::string& name, size_t n, double sr) {
    if (name == "silence") return silence(n);
    if (name == "impulse") return impulse(n);
    if (name == "dc") return dc(n);
    if (name == "ramp") return amplitudeRamp(n);
    if (name == "sine1k") return sine(n, sr, 1000.0);
    if (name == "sine_amp_sweep") return sineAmpSweep(n, sr, 1000.0);
    if (name == "log_sweep") return logSweep(n, sr);
    if (name == "white") return whiteNoise(n);
    if (name == "pink") return pinkNoise(n);
    if (name == "two_tone") return twoTone(n, sr);
    return {};
}

} // namespace abprobe
