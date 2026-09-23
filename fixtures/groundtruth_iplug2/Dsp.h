#pragma once
#include <cmath>

// Ground-truth DSP for fixture #2 (identical algorithms to ../groundtruth/Source/Dsp.h, no framework
// dependency): one TPT one-pole low-pass and one normalised tanh waveshaper. RTTI kept (virtual dtors).

namespace abgt
{

class TptLowpass
{
public:
    virtual ~TptLowpass() = default;

    void prepare (double sampleRate) { sr = sampleRate; reset(); setCutoff (cutoffHz); }
    void reset() { s = 0.0f; }

    void setCutoff (float hz)
    {
        cutoffHz = hz;
        const double clamped = hz < 1.0 ? 1.0 : (hz > sr * 0.499 ? sr * 0.499 : hz);
        g = (float) std::tan (3.14159265358979323846 * clamped / sr);
        G = g / (1.0f + g);
    }

    float process (float x) noexcept
    {
        const float v  = (x - s) * G;
        const float lp = v + s;
        s = lp + v;
        return lp;
    }

private:
    double sr = 48000.0;
    float cutoffHz = 8000.0f;
    float g = 0.1f, G = 0.1f, s = 0.0f;
};

class TanhShaper
{
public:
    virtual ~TanhShaper() = default;

    void setDrive (float d)
    {
        drive = d < 0.01f ? 0.01f : d;
        norm  = 1.0f / std::tanh (drive);
    }

    float process (float x) const noexcept { return std::tanh (drive * x) * norm; }
    float getDrive() const noexcept { return drive; }

private:
    float drive = 4.0f;
    float norm  = 1.0f / std::tanh (4.0f);
};

/** 2× oversampling with a short half-band FIR (framework-free stand-in for juce::dsp::Oversampling). */
class Oversampler2x
{
public:
    static constexpr int kTaps = 15;               // symmetric half-band FIR, latency (kTaps-1)/4 = 3.5 → reported 3 like the JUCE fixture
    void reset() { for (auto& v : up) v = 0.0f; for (auto& v : down) v = 0.0f; }
    int latency() const noexcept { return (kTaps - 1) / 4; }

    template <typename Fn>
    float process (float x, Fn&& fn) noexcept
    {
        // upsample: x, 0 → filter → fn each → filter → decimate
        const float a = fir (up, x * 2.0f);
        const float b = fir (up, 0.0f);
        const float ya = fn (a), yb = fn (b);
        const float y0 = fir (down, ya);
        fir (down, yb);
        return y0;
    }

private:
    static float fir (float* z, float x) noexcept
    {
        static const float h[kTaps] = { -0.0027f, 0.0f, 0.0149f, 0.0f, -0.0499f, 0.0f, 0.2871f, 0.5f, 0.2871f, 0.0f, -0.0499f, 0.0f, 0.0149f, 0.0f, -0.0027f };
        for (int i = kTaps - 1; i > 0; --i) z[i] = z[i - 1];
        z[0] = x;
        float acc = 0.0f;
        for (int i = 0; i < kTaps; ++i) acc += h[i] * z[i];
        return acc;
    }
    float up[kTaps] = {};
    float down[kTaps] = {};
};

} // namespace abgt
