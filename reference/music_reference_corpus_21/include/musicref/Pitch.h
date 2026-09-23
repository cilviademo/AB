#pragma once
#include "Common.h"
#include <vector>
namespace musicref {
// Simple autocorrelation estimator for reference/testing, not a production pitch engine.
inline double estimatePitchAutocorrelation(const std::vector<float>& x,double sampleRate,double minHz=50,double maxHz=2000){if(x.size()<8)return 0;size_t minLag=std::max<size_t>(1,size_t(sampleRate/maxHz));size_t maxLag=std::min(x.size()/2,size_t(sampleRate/minHz));double best=-1;size_t bestLag=0;for(size_t lag=minLag;lag<=maxLag;++lag){double s=0,e0=0,e1=0;for(size_t i=0;i+lag<x.size();++i){s+=x[i]*x[i+lag];e0+=x[i]*x[i];e1+=x[i+lag]*x[i+lag];}double n=s/(std::sqrt(e0*e1)+1e-12);if(n>best){best=n;bestLag=lag;}}return bestLag?sampleRate/bestLag:0;}
}
