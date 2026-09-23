#pragma once
#include <cstdint>
namespace musicref {
class WhiteNoise {
public:
    explicit WhiteNoise(uint32_t seed=0x12345678u):state_(seed?seed:1u){}
    float next(){state_^=state_<<13;state_^=state_>>17;state_^=state_<<5;return (float(state_)/float(0xffffffffu))*2.0f-1.0f;}
private:uint32_t state_;
};
}
