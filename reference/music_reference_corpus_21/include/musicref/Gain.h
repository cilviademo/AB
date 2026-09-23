#pragma once
#include "Common.h"
namespace musicref {
class GainStage {
public:
    void prepare(double sampleRate, double rampSeconds = 0.01) { smoother_.reset(sampleRate, rampSeconds); smoother_.setCurrentAndTarget(gain_); }
    void setGainLinear(double g) { gain_ = g; smoother_.setTarget(g); }
    void setGainDb(double db) { setGainLinear(dbToGain(db)); }
    float process(float x) { return float(x * smoother_.next()); }
private:
    double gain_ = 1.0;
    LinearSmoother smoother_;
};
}
