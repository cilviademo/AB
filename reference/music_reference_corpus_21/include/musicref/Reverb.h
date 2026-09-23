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
