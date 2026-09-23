#pragma once
#include "Common.h"
namespace musicref {
class EnvelopeFollower {
public:
    void prepare(double sr) { sr_ = sr; update(); }
    void setAttackRelease(double attackSec, double releaseSec) { attack_ = attackSec; release_ = releaseSec; update(); }
    float process(float x) {
        const float v = std::abs(x);
        const double c = v > env_ ? a_ : r_;
        env_ = float(c * env_ + (1.0 - c) * v);
        return env_;
    }
private:
    void update() { a_ = onePoleTimeCoefficient(attack_, sr_); r_ = onePoleTimeCoefficient(release_, sr_); }
    double sr_ = 48000.0, attack_ = 0.01, release_ = 0.1, a_ = 0.0, r_ = 0.0;
    float env_ = 0.0f;
};

class Compressor {
public:
    void prepare(double sr) { env_.prepare(sr); env_.setAttackRelease(attack_, release_); }
    void setThresholdDb(float v) { thresholdDb_ = v; }
    void setRatio(float v) { ratio_ = std::max(1.0f, v); }
    void setAttackRelease(double a, double r) { attack_ = a; release_ = r; env_.setAttackRelease(a, r); }
    void setMakeupDb(float v) { makeup_ = dbToGain(v); }
    float process(float x, float sidechain) {
        const float levelDb = gainToDb(env_.process(sidechain));
        float gainDb = 0.0f;
        if (levelDb > thresholdDb_) gainDb = (thresholdDb_ + (levelDb - thresholdDb_) / ratio_) - levelDb;
        return x * dbToGain(gainDb) * makeup_;
    }
    float process(float x) { return process(x, x); }
private:
    EnvelopeFollower env_;
    float thresholdDb_ = -18.0f, ratio_ = 4.0f, makeup_ = 1.0f;
    double attack_ = 0.01, release_ = 0.1;
};

class Limiter {
public:
    void setCeilingDb(float db) { ceiling_ = dbToGain(db); }
    float process(float x) const { return hardLimit(x); }
private:
    float hardLimit(float x) const { return clamp(x, -ceiling_, ceiling_); }
    float ceiling_ = 0.988553f; // about -0.1 dBFS
};

class Gate {
public:
    void prepare(double sr) { env_.prepare(sr); env_.setAttackRelease(0.002, 0.05); }
    void setThresholdDb(float db) { threshold_ = dbToGain(db); }
    void setFloorDb(float db) { floor_ = dbToGain(db); }
    float process(float x, float sidechain) { const float e = env_.process(sidechain); return x * (e >= threshold_ ? 1.0f : floor_); }
    float process(float x) { return process(x, x); }
private:
    EnvelopeFollower env_;
    float threshold_ = 0.01f, floor_ = 0.0f;
};

class AutoGain {
public:
    void prepare(double sr) { in_.prepare(sr); out_.prepare(sr); in_.setAttackRelease(0.1, 1.0); out_.setAttackRelease(0.1, 1.0); }
    float process(float dry, float processed) {
        const float i = std::max(in_.process(dry), 1.0e-6f);
        const float o = std::max(out_.process(processed), 1.0e-6f);
        return processed * clamp(i / o, 0.25f, 4.0f);
    }
private: EnvelopeFollower in_, out_;
};
}
