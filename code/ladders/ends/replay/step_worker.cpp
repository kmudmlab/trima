#include <stdint.h>
#include "api/compute/compute_kernel_api.h"
#include "api/compute/common.h"
// SHARED
using namespace step_ring;
void kernel_main() {
    const uint32_t worker=COMPILE_FOR_TRISC,epoch=get_common_arg_val<uint32_t>(4);
    static_assert(COMPILE_FOR_TRISC<3,"three TRISC workers");
    uint32_t bases[2]={get_common_arg_val<uint32_t>(5),get_common_arg_val<uint32_t>(6)};
    volatile uint32_t* sync[2]={(volatile uint32_t*)(bases[0]+SYNC),(volatile uint32_t*)(bases[1]+SYNC)};
    uint32_t next[2]={1,1},error=0,preferred=0;
    uint64_t count[2]={0,0}; ProbeStats stats[2];
#if COUNTERS
    uint64_t started=get_timestamp(),idle=0,source_idle=0,compute_ticks=0;
#endif
    uint32_t spins=0;
    while(true) {
        asm volatile("fence" ::: "memory");
        if(sync[0][EPOCH]==epoch && sync[1][EPOCH]==epoch) { break; }
        if(++spins==SPIN_LIMIT) { error=16; break; }
    }
    asm volatile("fence" ::: "memory");
    for(uint32_t ch=0;ch<2;ch++) { sync[ch][READY+worker]=epoch; }
    while(!error) {
        uint32_t channel=2; spins=0;
#if COUNTERS
        uint64_t wait_begin=get_timestamp(),last_tick=wait_begin;
#endif
        while(channel==2) {
            asm volatile("fence" ::: "memory");
            for(uint32_t choice=0;choice<2;choice++) {
                uint32_t ch=preferred^choice;
                if(sync[ch][slot_offset(next[ch])]==next[ch]) { channel=ch; break; }
            }
#if COUNTERS
            uint64_t now=get_timestamp();
            if(sync[0][PHASE]==PREP_SOURCE || sync[1][PHASE]==PREP_SOURCE) { source_idle+=now-last_tick; }
            last_tick=now;
#endif
            if(channel<2) { break; }
            if(sync[0][EOF_SEQ] && sync[1][EOF_SEQ] && next[0]>=sync[0][EOF_SEQ] && next[1]>=sync[1][EOF_SEQ]) { break; }
            if(sync[0][ERROR] || sync[1][ERROR]) { error=32; break; }
            if(++spins==SPIN_LIMIT) { error=64; break; }
        }
        PROF(idle+=get_timestamp()-wait_begin);
        if(channel==2) { break; }
        preferred=channel^1;
        uint32_t base=bases[channel],seq=next[channel],off=slot_offset(seq);
        auto sy=sync[channel];
        asm volatile("fence" ::: "memory");
        uint32_t batch=sy[off+2],arena=sy[off+3],source_u=sy[off+1];
        if(batch>BATCH || arena>1) { error=128; break; }
        auto jobs=(const Job*)(base+JOBS)+arena*BATCH;
        #if SOURCE_CONTEXTS == 2
        const uint32_t bank=sy[off+4];
        if(bank>=2) { error=128;break; }
        auto source=(const uint32_t*)(base+source_offset(bank));
        auto hash=(const uint32_t*)(base+hash_offset(bank));
#else
        auto source=(const uint32_t*)(base+SOURCE);
        auto hash=(const uint32_t*)(base+HASH);
#endif
        auto target=(const uint32_t*)(base+TARGET)+arena*ARENA_WORDS;
#if !TRISC_ON
        (void)base; (void)source_u; (void)jobs; (void)source; (void)hash; (void)target;
#endif
#if COUNTERS
        uint64_t compute_begin=get_timestamp();
#endif
#if TRISC_ON
#if STRESS
        if(worker==1 && seq%3==1) {
            for(volatile uint32_t delay=0;delay<STRESS;delay++) { asm volatile("nop"); }
        }
#endif
        for(uint32_t j=worker;j<batch;j+=4) {
            if(jobs[j].source_u!=source_u || jobs[j].degree>SOURCE_CAP || jobs[j].target_offset+jobs[j].length>ARENA_WORDS) { error=256; break; }
            count[channel]+=probe(jobs[j],source+jobs[j].source_offset,hash,target+jobs[j].target_offset,stats[channel]);
        }
#endif
        PROF(compute_ticks+=get_timestamp()-compute_begin);
        asm volatile("fence" ::: "memory"); sy[off+8+worker]=seq; ++next[channel];
    }
    for(uint32_t ch=0;ch<2;ch++) {
        auto sy=sync[ch]; uint32_t at=WORKER+worker*32;
        put64(sy,at,count[ch]);
        PROF(put64(sy,at+2,stats[ch].candidates); put64(sy,at+4,stats[ch].probes);
             put64(sy,at+8,ch==0?idle:0); put64(sy,at+10,ch==0?source_idle:0);
             put64(sy,at+12,ch==0?compute_ticks:0); put64(sy,at+14,ch==0?get_timestamp()-started:0);
             put64(sy,at+16,stats[ch].high_candidates);
             put64(sy,at+22,stats[ch].identity1); put64(sy,at+24,stats[ch].identity2));
        sy[at+6]=error; asm volatile("fence" ::: "memory"); sy[at+7]=epoch;
    }
}
