#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

namespace musicref {
constexpr double pi = 3.14159265358979323846264338327950288;

template <typename T> constexpr T clamp(T x, T lo, T hi) { return std::min(hi, std::max(lo, x)); }
template <typename T> inline T dbToGain(T db) { return std::pow(T(10), db / T(20)); }
template <typename T> inline T gainToDb(T gain) { return T(20) * std::log10(std::max(gain, T(1.0e-12))); }
template <typename T> inline T lerp(T a, T b, T t) { return a + (b - a) * t; }
inline double onePoleTimeCoefficient(double seconds, double sampleRate) {
    if (seconds <= 0.0 || sampleRate <= 0.0) return 0.0;
    return std::exp(-1.0 / (seconds * sampleRate));
}

class LinearSmoother {
public:
    void reset(double sampleRate, double seconds) { steps_ = std::max(1, int(sampleRate * seconds)); current_ = target_; remaining_ = 0; }
    void setCurrentAndTarget(double v) { current_ = target_ = v; remaining_ = 0; step_ = 0.0; }
    void setTarget(double v) { target_ = v; remaining_ = steps_; step_ = remaining_ > 0 ? (target_ - current_) / remaining_ : 0.0; }
    double next() { if (remaining_ > 0) { current_ += step_; --remaining_; } else current_ = target_; return current_; }
    double current() const { return current_; }
private:
    double current_ = 0.0, target_ = 0.0, step_ = 0.0;
    int steps_ = 1, remaining_ = 0;
};
}
