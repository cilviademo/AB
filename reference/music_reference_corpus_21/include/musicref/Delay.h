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
