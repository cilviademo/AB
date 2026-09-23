#pragma once
#include <cmath>

// Ground-truth DSP (SPEC §12). Deliberately small, named, and documented so the
// recovery pipeline has an unambiguous answer key: one TPT one-pole low-pass and
// one tanh waveshaper. RTTI is kept (virtual destructors) so class names survive.

namespace abgt
{

/** TPT (topology-preserving transform) one-pole low-pass, Zavalishin form. */
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

/** Normalised tanh waveshaper: y = tanh (drive * x) / tanh (drive). */
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

} // namespace abgt
