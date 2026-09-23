# Music Reference Codebook — 21-Plugin Corpus

> **Purpose:** A permanent clean-room code reference for the standard musical/DSP building blocks used by the 21-plugin recovery corpus. This is **reference/reconstruction code**, not recovered vendor source. Use it for inference, hypothesis testing, coding-agent context, and behavioral matching.

## Quick reference index

| Component | Source file | Purpose |
|---|---|---|
| `GainStage` | `Gain.h` | input/output/volume gain with smoothing |
| `Hard/soft clip families` | `Nonlinear.h` | hard, tanh, atan, cubic, diode-like |
| `BitCrusher` | `Nonlinear.h` | bit depth + sample hold |
| `EnvelopeFollower` | `Dynamics.h` | attack/release envelope |
| `Compressor` | `Dynamics.h` | downward compression |
| `Limiter` | `Dynamics.h` | reference ceiling limiter |
| `Gate` | `Dynamics.h` | reference gate |
| `AutoGain` | `Dynamics.h` | RMS/envelope level match |
| `Biquad` | `Filters.h` | LP/HP/BP/peak/shelves |
| `TPTOnePole` | `Filters.h` | TPT LP/HP |
| `StateVariableFilter` | `Filters.h` | low/band/high outputs |
| `FourPoleLadder` | `Filters.h` | generic nonlinear ladder |
| `Resonator` | `Filters.h` | bandpass resonator |
| `BaxandallReference` | `Filters.h` | shelf-pair tone reference |
| `SallenKeyReference` | `Filters.h` | generic two-pole low-pass reference |
| `FractionalDelayLine` | `Delay.h` | linear fractional delay |
| `StereoDelay` | `Delay.h` | stereo feedback delay |
| `PingPongDelay` | `Delay.h` | cross-feedback delay |
| `PreDelay` | `Delay.h` | short delay |
| `SineLFO` | `Modulation.h` | standard LFO |
| `Tremolo` | `Modulation.h` | amplitude modulation |
| `Chorus` | `Modulation.h` | modulated short delay |
| `Phaser` | `Modulation.h` | cascaded allpass phaser |
| `WowFlutter` | `Modulation.h` | dual-rate delay modulation |
| `SchroederReverb` | `Reverb.h` | comb/allpass algorithmic reverb |
| `FIRConvolver` | `Reverb.h` | direct FIR convolution reference |
| `MidSide/StereoWidth` | `Stereo.h` | M/S encode/decode + width |
| `WhiteNoise` | `Noise.h` | deterministic xorshift noise |
| `LinearResampler` | `Resampling.h` | offline linear interpolation |
| `SampleHoldReducer` | `Resampling.h` | sample-rate-reduction primitive |
| `Peak/RMS meters` | `Meters.h` | reference metering |
| `Pitch autocorrelation` | `Pitch.h` | simple pitch estimator |
| `Probe signals` | `ProbeSignals.h` | impulse/ramp/sine/sweep/noise |

## Fast lookup examples

- **Hard clipper:** search for `hardClip` in `Nonlinear.h`.
- **Soft saturation:** `tanhClip`, `atanClip`, `cubicSoftClip`, `diodeLikeClip`.
- **Bit/sample reduction:** `BitCrusher`, `SampleHoldReducer`.
- **Compressor / limiter / gate / autogain:** `Dynamics.h`.
- **Biquad / TPT / SVF / ladder / Baxandall / Sallen-Key:** `Filters.h`.
- **Delay / ping-pong / predelay:** `Delay.h`.
- **Chorus / phaser / tremolo / wow-flutter:** `Modulation.h`.
- **Reverb / FIR convolution:** `Reverb.h`.
- **Mid/side / width:** `Stereo.h`.
- **Resampling / pitch / meters / probes:** corresponding headers below.

## Reference rules

1. A class-name match from a recovered binary is only a **candidate mapping** to this code.
2. Promote a reference implementation into active reconstructed source only after static/runtime/behavioral evidence supports it.
3. Prefer original-vs-rebuild differential tests as the final arbiter.
4. Keep vendor/source provenance separate from this clean-room library.

## Hard clipper — immediate reference

```cpp
inline float hardClip(float x, float threshold = 1.0f) {
    return clamp(x, -threshold, threshold);
}
```

This is the corpus's generic clean-room hard-clip reference. It is intentionally simple so a recovery harness can test it against an original plugin and reject/refine it when needed.

# Complete code listings

## `CMakeLists.txt`

```cmake
cmake_minimum_required(VERSION 3.20)
project(music_reference_corpus LANGUAGES CXX)

add_library(musicref INTERFACE)
target_include_directories(musicref INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_features(musicref INTERFACE cxx_std_17)

option(MUSICREF_BUILD_TESTS "Build smoke tests" ON)
if(MUSICREF_BUILD_TESTS)
    add_executable(musicref_smoke tests/smoke.cpp)
    target_link_libraries(musicref_smoke PRIVATE musicref)
endif()

add_executable(musicref_example examples/reference_chain.cpp)
target_link_libraries(musicref_example PRIVATE musicref)
```

## `include/musicref/AnalogReference.h`

```cpp
#pragma once
#include "Filters.h"
#include "Nonlinear.h"
namespace musicref {
// Generic one-pole RC low-pass reference using the bilinear/TPT form.
class RCOnePoleReference {
public:void set(double sr,double hz){f_.set(sr,hz,TPTOnePole::Mode::LowPass);}float process(float x){return f_.process(x);}void reset(){f_.reset();}private:TPTOnePole f_;};
// Generic clean-room diode-clipping hypothesis helper. It is not a WDF implementation
// and must not be used as evidence for any observed chowdsp::wdft or MorphDiodeClipper code.
class DiodeClipperReference {public:void setDrive(float d){d_=d;}float process(float x){return diodeLikeClip(x,d_);}private:float d_=2.0f;};
}
```

## `include/musicref/Common.h`

```cpp
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
```

## `include/musicref/Delay.h`

```cpp
#pragma once
#include "Common.h"
#include <vector>
namespace musicref {
class FractionalDelayLine {
public:
    void prepare(double sr, double maxSeconds=2.0) { sr_=sr; data_.assign(std::max<size_t>(4,size_t(sr*maxSeconds)+4),0.0f); write_=0; }
    void reset(){std::fill(data_.begin(),data_.end(),0.0f); write_=0;}
    void push(float x){ if(data_.empty()) return; data_[write_]=x; write_=(write_+1)%data_.size(); }
    float readSeconds(double sec) const { return readSamples(sec*sr_); }
    float readSamples(double delay) const {
        if(data_.empty()) return 0.0f;
        delay=clamp(delay,1.0,double(data_.size()-3));
        double pos=double(write_)-delay; while(pos<0) pos+=data_.size();
        const size_t i0=size_t(pos)%data_.size(), i1=(i0+1)%data_.size();
        return lerp(data_[i0],data_[i1],float(pos-std::floor(pos)));
    }
private: double sr_=48000; std::vector<float> data_; size_t write_=0;
};

class StereoDelay {
public:
    void prepare(double sr){l_.prepare(sr,4);r_.prepare(sr,4);} 
    void set(double leftSec,double rightSec,float feedback,float mix){ld_=leftSec;rd_=rightSec;fb_=clamp(feedback,0.0f,0.99f);mix_=clamp(mix,0.0f,1.0f);} 
    void process(float& l,float& r){float dl=l_.readSeconds(ld_),dr=r_.readSeconds(rd_);l_.push(l+dl*fb_);r_.push(r+dr*fb_);l=lerp(l,dl,mix_);r=lerp(r,dr,mix_);} 
private:FractionalDelayLine l_,r_;double ld_=0.25,rd_=0.35;float fb_=0.3f,mix_=0.25f;
};

class PingPongDelay {
public:
    void prepare(double sr){l_.prepare(sr,4);r_.prepare(sr,4);} void set(double sec,float fb,float mix){d_=sec;fb_=clamp(fb,0.0f,0.99f);mix_=clamp(mix,0.0f,1.0f);} 
    void process(float& l,float& r){float dl=l_.readSeconds(d_),dr=r_.readSeconds(d_);l_.push(l+dr*fb_);r_.push(r+dl*fb_);l=lerp(l,dl,mix_);r=lerp(r,dr,mix_);} 
private:FractionalDelayLine l_,r_;double d_=0.3;float fb_=0.35f,mix_=0.3f;
};

class PreDelay {
public:
    void prepare(double sr){line_.prepare(sr,1);} void setMs(double ms){sec_=ms*0.001;} float process(float x){float y=line_.readSeconds(sec_);line_.push(x);return y;}
private:FractionalDelayLine line_;double sec_=0.02;
};
}
```

## `include/musicref/Dynamics.h`

```cpp
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
```

## `include/musicref/Filters.h`

```cpp
#pragma once
#include "Common.h"
namespace musicref {
class Biquad {
public:
    enum class Type { LowPass, HighPass, BandPass, Peak, LowShelf, HighShelf };
    void reset() { z1_ = z2_ = 0.0f; }
    void set(Type type, double sr, double hz, double q = 0.70710678118, double gainDb = 0.0) {
        hz = clamp(hz, 1.0, sr * 0.499);
        q = std::max(q, 1.0e-4);
        const double A = std::pow(10.0, gainDb / 40.0);
        const double w0 = 2.0 * pi * hz / sr;
        const double c = std::cos(w0), s = std::sin(w0);
        double alpha = s / (2.0 * q);
        double b0=1,b1=0,b2=0,a0=1,a1=0,a2=0;
        switch(type) {
            case Type::LowPass:  b0=(1-c)/2; b1=1-c; b2=(1-c)/2; a0=1+alpha; a1=-2*c; a2=1-alpha; break;
            case Type::HighPass: b0=(1+c)/2; b1=-(1+c); b2=(1+c)/2; a0=1+alpha; a1=-2*c; a2=1-alpha; break;
            case Type::BandPass: b0=s/2; b1=0; b2=-s/2; a0=1+alpha; a1=-2*c; a2=1-alpha; break;
            case Type::Peak:
                b0=1+alpha*A; b1=-2*c; b2=1-alpha*A; a0=1+alpha/A; a1=-2*c; a2=1-alpha/A; break;
            case Type::LowShelf: {
                const double sa = 2.0 * std::sqrt(A) * alpha;
                b0=A*((A+1)-(A-1)*c+sa); b1=2*A*((A-1)-(A+1)*c); b2=A*((A+1)-(A-1)*c-sa);
                a0=(A+1)+(A-1)*c+sa; a1=-2*((A-1)+(A+1)*c); a2=(A+1)+(A-1)*c-sa; break;
            }
            case Type::HighShelf: {
                const double sa = 2.0 * std::sqrt(A) * alpha;
                b0=A*((A+1)+(A-1)*c+sa); b1=-2*A*((A-1)+(A+1)*c); b2=A*((A+1)+(A-1)*c-sa);
                a0=(A+1)-(A-1)*c+sa; a1=2*((A-1)-(A+1)*c); a2=(A+1)-(A-1)*c-sa; break;
            }
        }
        b0_=float(b0/a0); b1_=float(b1/a0); b2_=float(b2/a0); a1_=float(a1/a0); a2_=float(a2/a0);
    }
    float process(float x) {
        const float y = b0_ * x + z1_;
        z1_ = b1_ * x - a1_ * y + z2_;
        z2_ = b2_ * x - a2_ * y;
        return y;
    }
private:
    float b0_=1,b1_=0,b2_=0,a1_=0,a2_=0,z1_=0,z2_=0;
};

class TPTOnePole {
public:
    enum class Mode { LowPass, HighPass };
    void set(double sr, double hz, Mode mode) { g_ = float(std::tan(pi * clamp(hz,1.0,sr*0.499) / sr)); mode_ = mode; }
    void reset() { s_ = 0.0f; }
    float process(float x) {
        const float v = (x - s_) * g_ / (1.0f + g_);
        const float lp = v + s_;
        s_ = lp + v;
        return mode_ == Mode::LowPass ? lp : x - lp;
    }
private: float g_=0.1f,s_=0; Mode mode_=Mode::LowPass;
};

class StateVariableFilter {
public:
    void set(double sr, double hz, double q) { g_=float(std::tan(pi*clamp(hz,1.0,sr*0.499)/sr)); k_=float(1.0/std::max(q,0.05)); }
    void reset(){ic1_=ic2_=0;}
    void process(float x, float& low, float& band, float& high) {
        const float a1 = 1.0f / (1.0f + g_*(g_+k_));
        const float a2 = g_*a1;
        const float a3 = g_*a2;
        const float v3 = x - ic2_;
        const float v1 = a1*ic1_ + a2*v3;
        const float v2 = ic2_ + a2*ic1_ + a3*v3;
        ic1_ = 2*v1 - ic1_; ic2_ = 2*v2 - ic2_;
        low=v2; band=v1; high=x-k_*v1-v2;
    }
private: float g_=0.1f,k_=1.4142f,ic1_=0,ic2_=0;
};

// Generic four-pole nonlinear ladder reference; not a model of any recovered vendor class.
class FourPoleLadder {
public:
    void set(double sr, double hz, float resonance) { a_=float(1.0-std::exp(-2.0*pi*clamp(hz,1.0,sr*0.45)/sr)); r_=clamp(resonance,0.0f,4.0f); }
    void reset(){s1_=s2_=s3_=s4_=0;}
    float process(float x) {
        x = std::tanh(x - r_*s4_);
        s1_ += a_*(x-s1_); s2_ += a_*(s1_-s2_); s3_ += a_*(s2_-s3_); s4_ += a_*(s3_-s4_);
        return s4_;
    }
private: float a_=0.1f,r_=0,s1_=0,s2_=0,s3_=0,s4_=0;
};

class Resonator {
public:
    void set(double sr, double hz, double q=8.0) { bq_.set(Biquad::Type::BandPass,sr,hz,q); }
    float process(float x){return bq_.process(x);} void reset(){bq_.reset();}
private: Biquad bq_;
};

class BaxandallReference {
public:
    void set(double sr, float bassDb, float trebleDb) { lo_.set(Biquad::Type::LowShelf,sr,120.0,0.707,bassDb); hi_.set(Biquad::Type::HighShelf,sr,4000.0,0.707,trebleDb); }
    float process(float x){return hi_.process(lo_.process(x));}
private:Biquad lo_,hi_;
};

class SallenKeyReference {
public:
    void setLowPass(double sr,double hz,double q=0.707){bq_.set(Biquad::Type::LowPass,sr,hz,q);} float process(float x){return bq_.process(x);} void reset(){bq_.reset();}
private:Biquad bq_;
};
}
```

## `include/musicref/Gain.h`

```cpp
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
```

## `include/musicref/Meters.h`

```cpp
#pragma once
#include "Common.h"
namespace musicref {
class PeakMeter{public:float process(float x){peak_=std::max(std::abs(x),peak_*0.9995f);return peak_;}void reset(){peak_=0;}private:float peak_=0;};
class RMSMeter{public:void setWindow(double sr,double sec){a_=float(onePoleTimeCoefficient(sec,sr));}float process(float x){v_=a_*v_+(1-a_)*x*x;return std::sqrt(std::max(v_,0.0f));}void reset(){v_=0;}private:float a_=0.99f,v_=0;};
}
```

## `include/musicref/Modulation.h`

```cpp
#pragma once
#include "Delay.h"
#include "Filters.h"
namespace musicref {
class SineLFO {
public:
    void prepare(double sr){sr_=sr;} void setHz(double hz){hz_=hz;} float next(){float y=std::sin(float(phase_));phase_+=2*pi*hz_/sr_;if(phase_>=2*pi)phase_-=2*pi;return y;}
private:double sr_=48000,hz_=1,phase_=0;
};

class Tremolo {
public:
    void prepare(double sr){lfo_.prepare(sr);} void set(double hz,float depth){lfo_.setHz(hz);depth_=clamp(depth,0.0f,1.0f);} float process(float x){return x*((1-depth_)+depth_*(0.5f+0.5f*lfo_.next()));}
private:SineLFO lfo_;float depth_=0.5f;
};

class Chorus {
public:
    void prepare(double sr){sr_=sr;line_.prepare(sr,0.1);lfo_.prepare(sr);} void set(float rateHz,float depthMs,float centerMs,float mix){lfo_.setHz(rateHz);depth_=depthMs*.001f;center_=centerMs*.001f;mix_=clamp(mix,0.0f,1.0f);} float process(float x){double d=center_+depth_*(0.5+0.5*lfo_.next());float y=line_.readSeconds(d);line_.push(x);return lerp(x,y,mix_);} 
private:double sr_=48000;FractionalDelayLine line_;SineLFO lfo_;float depth_=0.004f,center_=0.012f,mix_=0.5f;
};

class Phaser {
public:
    void prepare(double sr){sr_=sr;lfo_.prepare(sr);} void set(float rateHz,float minHz,float maxHz,float feedback,float mix){lfo_.setHz(rateHz);min_=minHz;max_=maxHz;fb_=clamp(feedback,-0.95f,0.95f);mix_=clamp(mix,0.0f,1.0f);} float process(float x){float t=.5f+.5f*lfo_.next();double hz=lerp(double(min_),double(max_),double(t));float y=x+z_*fb_;for(auto&i:s_){double a=(std::tan(pi*hz/sr_)-1.0)/(std::tan(pi*hz/sr_)+1.0);float o=float(-a*y+i);i=float(y+a*o);y=o;}z_=y;return lerp(x,y,mix_);} 
private:double sr_=48000;SineLFO lfo_;float min_=300,max_=1800,fb_=0.2f,mix_=0.5f,z_=0;float s_[4]{};
};

class WowFlutter {
public:
    void prepare(double sr){line_.prepare(sr,0.1);wow_.prepare(sr);flutter_.prepare(sr);} void set(float wowHz,float flutterHz,float depthMs){wow_.setHz(wowHz);flutter_.setHz(flutterHz);depth_=depthMs*.001f;} float process(float x){double mod=(0.75*wow_.next()+0.25*flutter_.next());double d=0.01+depth_*(0.5+0.5*mod);float y=line_.readSeconds(d);line_.push(x);return y;}
private:FractionalDelayLine line_;SineLFO wow_,flutter_;float depth_=0.003f;
};
}
```

## `include/musicref/Noise.h`

```cpp
#pragma once
#include <cstdint>
namespace musicref {
class WhiteNoise {
public:
    explicit WhiteNoise(uint32_t seed=0x12345678u):state_(seed?seed:1u){}
    float next(){state_^=state_<<13;state_^=state_>>17;state_^=state_<<5;return (float(state_)/float(0xffffffffu))*2.0f-1.0f;}
private:uint32_t state_;
};
}
```

## `include/musicref/Nonlinear.h`

```cpp
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
```

## `include/musicref/Pitch.h`

```cpp
#pragma once
#include "Common.h"
#include <vector>
namespace musicref {
// Simple autocorrelation estimator for reference/testing, not a production pitch engine.
inline double estimatePitchAutocorrelation(const std::vector<float>& x,double sampleRate,double minHz=50,double maxHz=2000){if(x.size()<8)return 0;size_t minLag=std::max<size_t>(1,size_t(sampleRate/maxHz));size_t maxLag=std::min(x.size()/2,size_t(sampleRate/minHz));double best=-1;size_t bestLag=0;for(size_t lag=minLag;lag<=maxLag;++lag){double s=0,e0=0,e1=0;for(size_t i=0;i+lag<x.size();++i){s+=x[i]*x[i+lag];e0+=x[i]*x[i];e1+=x[i+lag]*x[i+lag];}double n=s/(std::sqrt(e0*e1)+1e-12);if(n>best){best=n;bestLag=lag;}}return bestLag?sampleRate/bestLag:0;}
}
```

## `include/musicref/ProbeSignals.h`

```cpp
#pragma once
#include "Common.h"
#include "Noise.h"
#include <vector>
namespace musicref {
inline std::vector<float> impulse(size_t n,float amp=1.0f){std::vector<float>x(n,0);if(n)x[0]=amp;return x;}
inline std::vector<float> amplitudeRamp(size_t n,float lo=-2,float hi=2){std::vector<float>x(n);for(size_t i=0;i<n;++i)x[i]=lerp(lo,hi,n>1?float(i)/float(n-1):0);return x;}
inline std::vector<float> sine(size_t n,double sr,double hz,float amp=.5f){std::vector<float>x(n);for(size_t i=0;i<n;++i)x[i]=amp*std::sin(float(2*pi*hz*i/sr));return x;}
inline std::vector<float> logSweep(size_t n,double sr,double f0=20,double f1=20000,float amp=.5f){std::vector<float>x(n);double T=n/sr,K=T/std::log(f1/f0),L=2*pi*f0*K;for(size_t i=0;i<n;++i){double t=i/sr;x[i]=amp*std::sin(float(L*(std::exp(t/K)-1)));}return x;}
inline std::vector<float> whiteNoise(size_t n,float amp=.25f){WhiteNoise r;std::vector<float>x(n);for(auto&v:x)v=amp*r.next();return x;}
}
```

## `include/musicref/Resampling.h`

```cpp
#pragma once
#include "Common.h"
#include <vector>
namespace musicref {
inline std::vector<float> linearResample(const std::vector<float>& input,double ratio){if(input.empty()||ratio<=0)return{};size_t n=std::max<size_t>(1,size_t(std::ceil(input.size()*ratio)));std::vector<float>out(n);for(size_t i=0;i<n;++i){double p=i/ratio;size_t a=std::min<size_t>(size_t(p),input.size()-1),b=std::min(a+1,input.size()-1);out[i]=lerp(input[a],input[b],float(p-a));}return out;}
class SampleHoldReducer {
public:void setRatio(int r){r_=std::max(1,r);}float process(float x){if(c_++%r_==0)h_=x;return h_;}private:int r_=1,c_=0;float h_=0;};
}
```

## `include/musicref/Reverb.h`

```cpp
#pragma once
#include "Delay.h"
#include <array>
namespace musicref {
class SchroederReverb {
public:
    void prepare(double sr){sr_=sr;const double ds[4]={0.0297,0.0371,0.0411,0.0437};for(int i=0;i<4;++i){comb_[i].prepare(sr,0.1);delay_[i]=ds[i];}ap1_.prepare(sr,.02);ap2_.prepare(sr,.02);} 
    void set(float decay,float mix){fb_=clamp(decay,0.0f,0.95f);mix_=clamp(mix,0.0f,1.0f);} float process(float x){float sum=0;for(int i=0;i<4;++i){float y=comb_[i].readSeconds(delay_[i]);comb_[i].push(x+y*fb_);sum+=y;}sum*=.25f;sum=allpass(ap1_,sum,.005,0.5f);sum=allpass(ap2_,sum,.0017,0.5f);return lerp(x,sum,mix_);} 
private:static float allpass(FractionalDelayLine& l,float x,double d,float g){float z=l.readSeconds(d);float y=-g*x+z;l.push(x+g*y);return y;} double sr_=48000,delay_[4]{};std::array<FractionalDelayLine,4> comb_;FractionalDelayLine ap1_,ap2_;float fb_=0.75f,mix_=0.25f;
};

class FIRConvolver {
public:
    void setImpulse(std::vector<float> ir){ir_=std::move(ir);hist_.assign(ir_.size(),0);pos_=0;} float process(float x){if(ir_.empty())return x;hist_[pos_]=x;float y=0;size_t p=pos_;for(size_t i=0;i<ir_.size();++i){y+=ir_[i]*hist_[p];p=(p==0?hist_.size()-1:p-1);}pos_=(pos_+1)%hist_.size();return y;}
private:std::vector<float>ir_,hist_;size_t pos_=0;
};
}
```

## `include/musicref/Stereo.h`

```cpp
#pragma once
#include "Common.h"
namespace musicref {
inline void encodeMidSide(float l,float r,float& mid,float& side){constexpr float k=0.70710678118f;mid=(l+r)*k;side=(l-r)*k;}
inline void decodeMidSide(float mid,float side,float& l,float& r){constexpr float k=0.70710678118f;l=(mid+side)*k;r=(mid-side)*k;}
inline void applyStereoWidth(float& l,float& r,float width){float m,s;encodeMidSide(l,r,m,s);s*=width;decodeMidSide(m,s,l,r);}
}
```

## `include/musicref/musicref.h`

```cpp
#pragma once
#include "Common.h"
#include "Gain.h"
#include "Nonlinear.h"
#include "Dynamics.h"
#include "Filters.h"
#include "Delay.h"
#include "Modulation.h"
#include "Reverb.h"
#include "Stereo.h"
#include "Noise.h"
#include "Resampling.h"
#include "Meters.h"
#include "Pitch.h"
#include "AnalogReference.h"
#include "ProbeSignals.h"
```

## `examples/reference_chain.cpp`

```cpp
#include <musicref/musicref.h>
#include <iostream>
int main(){
    musicref::GainStage input; input.prepare(48000); input.setGainDb(6.0);
    musicref::Biquad tone; tone.set(musicref::Biquad::Type::LowPass,48000,9000,0.707);
    musicref::Compressor comp; comp.prepare(48000); comp.setThresholdDb(-12); comp.setRatio(3);
    float x=.5f;
    for(int i=0;i<16;++i){ float y=input.process(x); y=tone.process(y); y=musicref::tanhClip(y,1.5f); y=comp.process(y); std::cout<<y<<"\n"; }
}
```

## `tests/smoke.cpp`

```cpp
#include <musicref/musicref.h>
#include <cassert>
#include <cmath>
#include <iostream>
int main(){
    using namespace musicref;
    assert(hardClip(2.0f)==1.0f);
    Biquad lp; lp.set(Biquad::Type::LowPass,48000,1000); float y=0; for(int i=0;i<128;++i)y=lp.process(i==0?1.0f:0.0f); assert(std::isfinite(y));
    Compressor c;c.prepare(48000);for(int i=0;i<128;++i)assert(std::isfinite(c.process(.5f)));
    Chorus ch;ch.prepare(48000);assert(std::isfinite(ch.process(.2f)));
    SchroederReverb rv;rv.prepare(48000);assert(std::isfinite(rv.process(.2f)));
    std::cout<<"musicref smoke OK\n";
}
```

# Catalog appendix

The full corpus ZIP also contains `catalog/observed_symbols.json`, `parameter_state_catalog.json`, `plugin_families.json`, and other machine-readable mappings. Those catalogs are deliberately not duplicated here because this file is the **code reference book**; the JSON files remain the authoritative evidence/index layer.
