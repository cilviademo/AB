#pragma once
#include "Common.h"
namespace musicref {
class PeakMeter{public:float process(float x){peak_=std::max(std::abs(x),peak_*0.9995f);return peak_;}void reset(){peak_=0;}private:float peak_=0;};
class RMSMeter{public:void setWindow(double sr,double sec){a_=float(onePoleTimeCoefficient(sec,sr));}float process(float x){v_=a_*v_+(1-a_)*x*x;return std::sqrt(std::max(v_,0.0f));}void reset(){v_=0;}private:float a_=0.99f,v_=0;};
}
