#include <stdint.h>

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
    stats.candidates+=job.length;return 0;
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

using namespace step_ring;
void replay_kernel() {
    const uint32_t gx=get_common_arg_val<uint32_t>(0),cores=get_common_arg_val<uint32_t>(1),n=get_common_arg_val<uint32_t>(2);
    const uint32_t cid=get_absolute_logical_y()*gx+get_absolute_logical_x(),id=2*cid+CHANNEL;
    const uint32_t epoch=get_common_arg_val<uint32_t>(4);
    auto output=0;
    uintptr_t base=get_write_ptr(CHANNEL);
    auto sync=(volatile uint32_t*)(base+SYNC);
    auto result=(uint32_t*)(base+OUTPUT);
    auto tags=(uint32_t*)(base+TAGS);
    auto cache=(uint32_t*)(base+CACHE);
    auto sourcebuf=(uint32_t*)(base+SOURCE);
    auto hash=(uint32_t*)(base+HASH);
    auto used=(uint32_t*)(base+USED);
    auto meta=(uint32_t*)(base+META);
    auto refs=(Ref*)(base+REFS);
    auto tasks=(uint32_t*)(base+TASKS);
    auto pairs=(uint32_t*)(base+PAIRS);
    for(uint32_t j=0;j<1024;j++) { sync[j]=0; result[j]=0; }
    for(uint32_t j=0;j<96;j++) { tags[j]=0xffffffffu; }
    for(uint32_t j=0;j<HASH_SIZE;j++) { hash[j]=0; }
    uint32_t error=0,seq=0,nused=0; (void)nused;
    uint64_t owncount=0;
    ProbeStats stats;
#if COUNTERS
    uint64_t started=uint64_t(0),misses[3]={},requests[3]={},bytes[3]={},barriers=0;
    uint64_t ack_slot=0,ack_source=0,source_ticks=0,target_ticks=0,copy_ticks=0,sources=0,batches=0;
#endif
     sync[EPOCH]=epoch;
    auto wait_ack=[&](uint32_t,bool)->bool { return !error; };
    auto fetch=[&](uint32_t which,uint64_t lo,uint64_t hi,uint32_t* dst)->uint32_t* {
#if DIRECT
        range_read(which,lo,hi,(uintptr_t)dst);
#if COUNTERS
        uint64_t a=lo&~uint64_t(15),b=(hi+15)&~uint64_t(15);
        bytes[which]+=(b-a)*4;
        if(b>a) { requests[which]+=(b-1)/256-a/256+1; }
#endif
#else
        uint32_t offset=which==0?0:(which==1?16:80),slots=which==1?64:16;
        uint32_t* out=dst+lo%16;
        for(uint64_t p=lo;p<hi;) {
            uint32_t page=p/256,slot=page%slots,at=offset+slot;
            if(tags[at]!=page) {
                read_page(which,page,(uintptr_t)(cache+at*256)); noc_async_read_barrier(); tags[at]=page;
                PROF(++misses[which]; ++barriers);
            }
            uint32_t take=256-p%256;
            if(take>hi-p) { take=hi-p; }
#if COUNTERS
            uint64_t copy_start=uint64_t(0);
#endif
            for(uint32_t j=0;j<take;j++) { out[j]=cache[at*256+p%256+j]; }
            PROF(if(uintptr_t(dst)>=base+TARGET && uintptr_t(dst)<base+JOBS) { copy_ticks+=uint64_t(0)-copy_start; });
            out+=take; p+=take;
        }
#endif
        return dst+lo%16;
    };
    auto barrier=[&]() {
#if DIRECT
        noc_async_read_barrier(); PROF(++barriers);
#endif
    };
    for(uint64_t uu=id;uu<n && !error;uu+=cpu_engines) {
        PROF(sync[PHASE]=PREP_SOURCE);
#if COUNTERS
        uint64_t source_start=uint64_t(0);
#endif
        uint32_t u=uu;
        fetch(2,u,u+2,pairs); fetch(0,u,u+2,pairs+32); barrier();
        uint32_t first=pairs[u%16],last=pairs[u%16+1];
        if(first==last) { PROF(source_ticks+=uint64_t(0)-source_start); continue; }
        uint32_t a=pairs[32+u%16],degree=pairs[33+u%16]-a;
        if(degree>SOURCE_CAP || !degree) { error=3; break; }
        auto src=fetch(1,a,a+degree,sourcebuf); barrier();
        if(degree>128) { nused=0; }
        PROF(++sources; source_ticks+=uint64_t(0)-source_start);
        uint32_t source_batches=0;
        for(uint32_t t0=first;t0<last && !error;t0+=BATCH) {
            PROF(sync[PHASE]=FETCH_TARGET);
#if COUNTERS
            uint64_t target_start=uint64_t(0);
#endif
            uint32_t cnt=last-t0; if(cnt>BATCH) { cnt=BATCH; }
            auto ids=fetch(2,uint64_t(n)+1+t0,uint64_t(n)+1+t0+cnt,tasks); barrier();
            for(uint32_t k=0;k<cnt;k++) { fetch(0,ids[k],ids[k]+2,meta+k*32); }
            barrier();
            for(uint32_t k=0;k<cnt;k++) {
                uint32_t v=ids[k],lo=meta[k*32+v%16],hi=meta[k*32+v%16+1];
                if(hi<lo || hi-lo+32>ARENA_WORDS) { error=4; break; }
                refs[k]={lo,hi,0,0};
            }
            PROF(target_ticks+=uint64_t(0)-target_start);
            for(uint32_t k=0;k<cnt && !error;) {
                if(seq>=0xfffffffeu) { error=5; break; }
                uint32_t next=seq+1,arena=(next-1)%2,off=slot_offset(next);
                if(next>2 && !wait_ack(next-2,false)) { break; }
                auto jobs=(Job*)(base+JOBS)+arena*BATCH;
                uint32_t k1=plan(refs,k,cnt,jobs,u,degree,a%16,t0);
                if(k1==k) { error=6; break; }
                auto target=(uint32_t*)(base+TARGET)+arena*ARENA_WORDS;
                PROF(sync[PHASE]=FETCH_TARGET);
#if COUNTERS
                uint64_t fetch_start=uint64_t(0);
#endif
                for(uint32_t j=k;j<k1;j++) {
                    if(refs[j].hi>refs[j].lo) { fetch(1,refs[j].lo,refs[j].hi,target+jobs[j-k].target_offset-refs[j].lo%16); }
                }
                barrier(); PROF(target_ticks+=uint64_t(0)-fetch_start);
#if STRESS
                if(CHANNEL==0 && next%3==0) {
                    for(volatile uint32_t delay=0;delay<STRESS;delay++) { asm volatile("nop"); }
                }
#endif
                uint32_t batch=k1-k;
                sync[off+1]=u; sync[off+2]=batch; sync[off+3]=arena;
                 sync[off]=next; seq=next;
                PROF(++batches; put64(result,224+batch*2,get64(result,224+batch*2)+1); sync[PHASE]=COMPUTE);
                ++source_batches;
                for(uint32_t j=(TRISC_ON?3:0);j<batch;j+=(TRISC_ON?4:1)) {
                    owncount+=probe(jobs[j],src,hash,target+jobs[j].target_offset,stats);
                }
                k=k1;
            }
        }
        PROF(sync[PHASE]=DRAIN);
        if(!wait_ack(seq,true)) { break; }
        // All consumers visit each channel in sequence: ACK(seq) also retires seq-1.
        PROF(put64(result,128+source_bin(source_batches)*2,get64(result,128+source_bin(source_batches)*2)+1));
    }
    if(!error) { wait_ack(seq,true); }
    sync[ERROR]=error; PROF(sync[PHASE]=FINISHED);
     sync[EOF_SEQ]=seq+1;
    uint64_t total=owncount,candidates=stats.candidates,probes=stats.probes;
    for(uint32_t w=0;w<3;w++) {
        uint32_t at=WORKER+w*32; total+=get64(sync,at); error|=sync[at+6];
        PROF(candidates+=get64(sync,at+2); probes+=get64(sync,at+4);
             put64(result,34+w*2,get64(sync,at+2));
             for(uint32_t j=0;j<6;j++) { put64(result,64+w*16+j*2,get64(sync,at+8+j*2)); });
    }
    put64(result,0,total);
    PROF(put64(result,2,sources); put64(result,4,candidates); put64(result,6,probes);
         for(uint32_t j=0;j<3;j++) { put64(result,8+j*2,misses[j]); put64(result,360+j*2,requests[j]); put64(result,366+j*2,bytes[j]); }
         put64(result,32,stats.candidates); put64(result,40,ack_slot); put64(result,42,ack_source);
         put64(result,44,source_ticks); put64(result,46,target_ticks); put64(result,48,copy_ticks);
         put64(result,50,uint64_t(0)-started); put64(result,52,batches); put64(result,54,barriers);
         put64(result,56,stats.high_candidates));
    result[22]=error; result[24]=id; result[25]=0x53545243;
    noc_async_write_tile(id,output,(uintptr_t)result); noc_async_write_barrier();
}
