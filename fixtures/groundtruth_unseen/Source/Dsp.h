#pragma once
#include <cmath>

// Unseen fixture DSP (ADDENDUM B8 test 1). Different implementations from the first fixture on purpose:
// an RC one-pole (not TPT) and an arctangent shaper (not tanh). RTTI kept via virtual destructors.
namespace abus
{

/** Plain RC one-pole low-pass: y += g * (x - y), g = 1 - exp(-2π fc / fs). */
class OnePoleLP
{
public:
    virtual ~OnePoleLP() = default;

    void prepare (double sampleRate) { fs = sampleRate; y = 0.0f; setCutoff (fc); }
    void setCutoff (float hz)
    {
        fc = hz;
        const double c = hz < 1.0 ? 1.0 : (hz > fs * 0.49 ? fs * 0.49 : hz);
        g = (float) (1.0 - std::exp (-2.0 * 3.14159265358979323846 * c / fs));
    }
    float process (float x) noexcept { y += g * (x - y); return y; }

private:
    double fs = 48000.0;
    float fc = 12000.0f, g = 0.8f, y = 0.0f;
};

/** Arctangent shaper: y = (2/π) · atan (amount · x); hard mode clamps instead. */
class AtanShaper
{
public:
    virtual ~AtanShaper() = default;

    void setAmount (float a) noexcept { amount = a < 0.01f ? 0.01f : a; }
    void setHard (bool h) noexcept { hard = h; }

    float process (float x) const noexcept
    {
        const float u = amount * x;
        if (hard)
            return u < -1.0f ? -1.0f : (u > 1.0f ? 1.0f : u);
        return 0.63661977236758134f * std::atan (u);
    }

    float getAmount() const noexcept { return amount; }

private:
    float amount = 3.0f;
    bool hard = false;
};

} // namespace abus
