#pragma once
#include <stdint.h>
// ids are increasing. Offsets are byte offsets into a packed raw staging area.
// emit(lo, hi, dst_offset) uses word addresses; read_row_range splits 16 KiB pages.
template<class Emit>
static inline uint32_t plan_metadata(const uint32_t* ids, uint32_t count,
                                    uint32_t threshold, uint32_t* offsets,
                                    uint32_t stride, Emit emit) {
    uint32_t lo=0, hi=0, bytes=0;
    for(uint32_t k=0; k<count; ++k) {
        const uint32_t v=ids[k];
        if(v>=threshold) { break; }
        const uint32_t a=v&~15u, b=(v+17u)&~15u;
        if(hi && a>hi+13u*16u) {
            emit(lo,hi,bytes);
            bytes+=(hi-lo)*4u;
            lo=hi=0;
        }
        if(!hi) { lo=a; }
        hi=b>hi?b:hi;
        offsets[k*stride]=bytes+(v-lo)*4u;
    }
    if(hi) { emit(lo,hi,bytes); bytes+=(hi-lo)*4u; }
    return bytes;
}
