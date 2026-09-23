#pragma once
#include "Common.h"
namespace musicref {
inline float hardClip(float x, float threshold = 1.0f) { return clamp(x, -threshold, threshold); }
inline float tanhClip(float x, float drive = 1.0f) { return std::tanh(x * drive); }
inline float atanClip(float x, float drive = 1.0f) { return float((2.0 / pi) * std::atan(double(x * drive))); }
inline float cubicSoftClip(float x) {
    x = clamp(x, -1.5f, 1.5f);
    if (x <= -1.0f) return -2.0f / 3.0f;
    if (x >= 1.0f) return 2.0f / 3.0f;
    return x - (x * x * x) / 3.0f;
}
inline float diodeLikeClip(float x, float drive = 1.0f, float asymmetry = 0.0f) {
    const float d = std::max(0.001f, drive);
    const float bias = asymmetry * 0.25f;
    const float y = std::tanh((x + bias) * d) - std::tanh(bias * d);
    return y;
}

class BitCrusher {
public:
    void setBits(int bits) { bits_ = std::max(1, std::min(24, bits)); }
    void setHoldSamples(int n) { hold_ = std::max(1, n); }
    float process(float x) {
        if (counter_++ % hold_ == 0) {
            const float levels = float((1u << std::min(bits_, 23)) - 1u);
            held_ = std::round(clamp(x, -1.0f, 1.0f) * levels) / levels;
        }
        return held_;
    }
private:
    int bits_ = 12, hold_ = 1, counter_ = 0;
    float held_ = 0.0f;
};

// Deliberately simple 2x reference oversampler for hypothesis/testing only.
// Use a production half-band/polyphase implementation for final fidelity work.
template <class Fn> inline float referenceOversample2x(float previous, float x, Fn&& nonlinear) {
    const float mid = 0.5f * (previous + x);
    return 0.5f * (nonlinear(mid) + nonlinear(x));
}
}
