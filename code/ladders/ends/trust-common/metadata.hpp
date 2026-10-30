#pragma once
#include <stdint.h>
// At most 64 IDs. Preserve original job order while planning sorted addresses.
// emit uses word coordinates and packed byte offsets; caller splits 16 KiB pages.
template<class Emit>
inline uint32_t plan_pairs(const uint32_t* ids, uint32_t count, uint32_t threshold,
                           uint32_t* mapping, Emit emit) {
    uint32_t sorted[64], ordinal[64], used=0;
    for(uint32_t k=0;k<count;++k) {
        if(ids[k]>=threshold) { mapping[k]=0xffffffffu; continue; }
        uint32_t at=used;
        while(at && sorted[at-1]>ids[k]) {
            sorted[at]=sorted[at-1]; ordinal[at]=ordinal[at-1]; --at;
        }
        sorted[at]=ids[k]; ordinal[at]=k; ++used;
    }
    uint32_t lo=0,hi=0,bytes=0;
    for(uint32_t k=0;k<used;++k) {
        uint32_t a=sorted[k]&~15u,b=(sorted[k]+17u)&~15u;
        if(hi && a>hi+13u*16u) {
            emit(lo,hi,bytes); bytes+=(hi-lo)*4u; lo=hi=0;
        }
        if(!hi) { lo=a; }
        if(b>hi) { hi=b; }
        mapping[ordinal[k]]=bytes+(sorted[k]-lo)*4u;
    }
    if(hi) { emit(lo,hi,bytes); bytes+=(hi-lo)*4u; }
    return bytes;
}
