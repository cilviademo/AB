#pragma once
#include "Common.h"
namespace musicref {
inline void encodeMidSide(float l,float r,float& mid,float& side){constexpr float k=0.70710678118f;mid=(l+r)*k;side=(l-r)*k;}
inline void decodeMidSide(float mid,float side,float& l,float& r){constexpr float k=0.70710678118f;l=(mid+side)*k;r=(mid-side)*k;}
inline void applyStereoWidth(float& l,float& r,float width){float m,s;encodeMidSide(l,r,m,s);s*=width;decodeMidSide(m,s,l,r);}
}
