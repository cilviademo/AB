#pragma once
#include "Common.h"
#include <vector>
namespace musicref {
inline std::vector<float> linearResample(const std::vector<float>& input,double ratio){if(input.empty()||ratio<=0)return{};size_t n=std::max<size_t>(1,size_t(std::ceil(input.size()*ratio)));std::vector<float>out(n);for(size_t i=0;i<n;++i){double p=i/ratio;size_t a=std::min<size_t>(size_t(p),input.size()-1),b=std::min(a+1,input.size()-1);out[i]=lerp(input[a],input[b],float(p-a));}return out;}
class SampleHoldReducer {
public:void setRatio(int r){r_=std::max(1,r);}float process(float x){if(c_++%r_==0)h_=x;return h_;}private:int r_=1,c_=0;float h_=0;};
}
