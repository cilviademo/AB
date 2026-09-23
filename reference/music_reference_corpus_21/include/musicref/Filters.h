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
