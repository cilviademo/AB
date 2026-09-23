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
