#pragma once
#include <stdint.h>
#ifndef COUNTERS
#define COUNTERS 0
#endif
#if COUNTERS
#define PROF(x) do { x; } while (0)
#else
#define PROF(x) do {} while (0)
#endif
namespace step_ring {
constexpr uint32_t SYNC=4096,CACHE=8192,TAGS=106496,SOURCE=108032,USED=117120,HASH=126080;
constexpr uint32_t META=191616,REFS=199808,TASKS=200832,PAIRS=201216,TARGET=201472,JOBS=332544,OUTPUT=336640;
constexpr uint32_t CHANNEL_BYTES=344064,SOURCE_CAP=2240,HASH_SIZE=16384,ARENA_WORDS=16384,BATCH=64;
constexpr uint32_t EPOCH=0,EOF_SEQ=1,ERROR=2,PHASE=3,READY=4,WORKER=128;
constexpr uint32_t PREP_SOURCE=1,FETCH_TARGET=2,COMPUTE=3,DRAIN=4,FINISHED=5;
constexpr uint32_t SPIN_LIMIT=1000000000;
struct Job { uint32_t source_u,degree,source_offset,target_offset,length,path,ordinal,mask; };
static_assert(sizeof(Job)==32,"descriptor size");
struct Ref { uint32_t lo,hi,off,pad; };
struct ProbeStats { uint64_t candidates=0,probes=0,high_candidates=0; };
inline uint32_t slot_offset(uint32_t seq) { return 16+((seq-1)%2)*16; }
inline uint32_t source_bin(uint32_t batches) {
    if(batches<=4) { return batches; }
    uint32_t upper=8,bin=5;
    while(batches>upper && bin<34) { upper=upper>0x7fffffffu?0xffffffffu:upper*2; ++bin; }
    return bin;
}
inline void put64(volatile uint32_t* p,uint32_t word,uint64_t v) { p[word]=uint32_t(v); p[word+1]=uint32_t(v>>32); }
inline uint64_t get64(const volatile uint32_t* p,uint32_t word) { return uint64_t(p[word])+(uint64_t(p[word+1])<<32); }
inline void build_hash(const uint32_t* src,uint32_t degree,uint32_t* hash,uint32_t* used,uint32_t& nused) {
    for(uint32_t j=0;j<nused;j++) { hash[used[j]]=0; }
    nused=0;
    for(uint32_t j=0;j<degree;j++) {
        uint32_t y=src[j],key=y+1,at=(y^(y>>16))&(HASH_SIZE-1);
        while(hash[at] && hash[at]!=key) { at=(at+1)&(HASH_SIZE-1); }
        if(!hash[at]) { hash[at]=key; used[nused++]=at; }
    }
}
inline uint32_t probe(const Job& job,const uint32_t* src,const uint32_t* hash,const uint32_t* target,ProbeStats& stats) {
    uint32_t count=0;
    PROF(stats.candidates+=job.length);
    if(!job.path) {
        uint32_t lower=0;
        for(uint32_t x=0;x<job.length;x++) {
            uint32_t key=target[x],lo=lower,hi=job.degree;
            while(lo<hi) {
                uint32_t mid=(lo+hi)/2; PROF(++stats.probes);
                if(src[mid]<key) { lo=mid+1; } else { hi=mid; }
            }
            if(lo<job.degree && src[lo]==key) { ++count; }
            lower=lo;
        }
    } else {
        PROF(stats.high_candidates+=job.length);
        uint32_t x=0;
        for(;x+4<=job.length;x+=4) {
            uint32_t keys[4],slots[4],values[4];
#pragma GCC unroll 4
            for(uint32_t z=0;z<4;z++) {
                uint32_t y=target[x+z]; keys[z]=y+1; slots[z]=(y^(y>>16))&job.mask; values[z]=hash[slots[z]];
            }
#pragma GCC unroll 4
            for(uint32_t z=0;z<4;z++) {
                uint32_t value=values[z],at=slots[z];
                while(value && value!=keys[z]) { at=(at+1)&job.mask; value=hash[at]; PROF(++stats.probes); }
                if(value==keys[z]) { ++count; }
            }
        }
        for(;x<job.length;x++) {
            uint32_t y=target[x],key=y+1,at=(y^(y>>16))&job.mask,value;
            while((value=hash[at]) && value!=key) { at=(at+1)&job.mask; PROF(++stats.probes); }
            if(value==key) { ++count; }
        }
    }
    return count;
}
// Complete rows only. Same packing for both supplies and both processor configurations.
inline uint32_t plan(const Ref* refs,uint32_t first,uint32_t end,Job* jobs,uint32_t u,uint32_t degree,uint32_t source_offset,uint32_t ordinal) {
    uint32_t words=0,k=first;
    for(;k<end;k++) {
        uint32_t lo=refs[k].lo,hi=refs[k].hi;
        uint32_t need=hi==lo?0:((hi+15)&~15u)-(lo&~15u);
        if(words+need>ARENA_WORDS) { break; }
        jobs[k-first]={u,degree,source_offset,words+lo%16,hi-lo,uint32_t(degree>128),ordinal+k,HASH_SIZE-1};
        words+=need;
    }
    return k;
}
} // namespace step_ring
