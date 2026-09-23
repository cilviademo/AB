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
