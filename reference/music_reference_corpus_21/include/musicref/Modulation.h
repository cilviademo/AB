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
