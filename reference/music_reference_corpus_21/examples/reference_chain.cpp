#include <musicref/musicref.h>
#include <iostream>
int main(){
    musicref::GainStage input; input.prepare(48000); input.setGainDb(6.0);
    musicref::Biquad tone; tone.set(musicref::Biquad::Type::LowPass,48000,9000,0.707);
    musicref::Compressor comp; comp.prepare(48000); comp.setThresholdDb(-12); comp.setRatio(3);
    float x=.5f;
    for(int i=0;i<16;++i){ float y=input.process(x); y=tone.process(y); y=musicref::tanhClip(y,1.5f); y=comp.process(y); std::cout<<y<<"\n"; }
}
