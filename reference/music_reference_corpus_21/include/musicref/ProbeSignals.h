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
