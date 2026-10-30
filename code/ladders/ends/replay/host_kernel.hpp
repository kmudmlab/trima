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
#ifndef FAMILY
#define FAMILY 1
#endif
#ifndef SOURCE_CONTEXTS
#define SOURCE_CONTEXTS 1
#endif
static_assert(SOURCE_CONTEXTS==1 || (SOURCE_CONTEXTS==2 && (FAMILY==1 || FAMILY==4)),"source-centered contexts only");
namespace step_ring {
inline uint32_t hash_slot(uint32_t y,uint32_t mask) { return uint32_t(y*0x9E3779B1u)>>__builtin_clz(mask); }
constexpr uint32_t SYNC=4096,CACHE=8192,TAGS=106496,SOURCE=108032,USED=117120,HASH=126080;
constexpr uint32_t META=191616,REFS=199808,TASKS=200832,PAIRS=201216,TARGET=201472,JOBS=332544,OUTPUT=336640;
constexpr uint32_t CHANNEL_BYTES=(SOURCE_CONTEXTS==2?495616:409600),SOURCE_CAP=2240,HASH_SIZE=16384,ARENA_WORDS=16384,BATCH=64;
constexpr uint32_t MERGE=344064, MAPPING=405504, MERGE_BYTES=61440;
// Bank 1 is appended; all bank-0 and ring/arena offsets stay frozen.
constexpr uint32_t SOURCE1=409600,USED1=418688,HASH1=427648;
inline uint32_t source_offset(uint32_t bank) { return bank?SOURCE1:SOURCE; }
inline uint32_t used_offset(uint32_t bank) { return bank?USED1:USED; }
inline uint32_t hash_offset(uint32_t bank) { return bank?HASH1:HASH; }
static_assert(HASH1+HASH_SIZE*4<=495616,"bank1 bounds");
constexpr uint32_t EPOCH=0,EOF_SEQ=1,ERROR=2,PHASE=3,READY=4,WORKER=128;
constexpr uint32_t PREP_SOURCE=1,FETCH_TARGET=2,COMPUTE=3,DRAIN=4,FINISHED=5;
constexpr uint32_t SPIN_LIMIT=1000000000;
struct Job { uint32_t source_u,degree,source_offset,target_offset,length,path,ordinal,mask; };
static_assert(sizeof(Job)==32,"descriptor size");
struct Ref { uint32_t lo,hi,off,pad; };
struct ProbeStats { uint64_t candidates=0,probes=0,high_candidates=0,identity1=0,identity2=0; };
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
        uint32_t y=src[j],key=y+1,at=hash_slot(y,HASH_SIZE-1);
        while(hash[at] && hash[at]!=key) { at=(at+1)&(HASH_SIZE-1); }
        if(!hash[at]) { hash[at]=key; used[nused++]=at; }
    }
}
inline uint32_t probe(const Job& job,const uint32_t* src,const uint32_t* hash,const uint32_t* target,ProbeStats& stats) {
    uint32_t count=0;
#if FAMILY == 1
    PROF(stats.candidates+=job.length;
         uint64_t len=job.length; uint64_t a=uint64_t(job.ordinal)+1;
         stats.identity1+=len*a*0x9e3779b1ull+len*(len-1)/2;
         stats.identity2+=len*(uint64_t(job.source_u)+1)*a+len*(len-1)*(2*len-1)/6;);
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
                uint32_t y=target[x+z]; keys[z]=y+1; slots[z]=hash_slot(y,job.mask); values[z]=hash[slots[z]];
            }
#pragma GCC unroll 4
            for(uint32_t z=0;z<4;z++) {
                uint32_t value=values[z],at=slots[z];
                while(value && value!=keys[z]) { at=(at+1)&job.mask; value=hash[at]; PROF(++stats.probes); }
                if(value==keys[z]) { ++count; }
            }
        }
        for(;x<job.length;x++) {
            uint32_t y=target[x],key=y+1,at=hash_slot(y,job.mask),value;
            while((value=hash[at]) && value!=key) { at=(at+1)&job.mask; PROF(++stats.probes); }
            if(value==key) { ++count; }
        }
    }
#elif FAMILY == 4
    PROF(stats.candidates+=job.length; stats.high_candidates+=job.length;
         for(uint32_t x=0;x<job.length;++x) {
             const uint64_t u=uint64_t(job.source_u)+1; const uint64_t v=uint64_t(src[job.ordinal])+1; const uint64_t w=uint64_t(target[x])+1;
             stats.identity1+=u*0x9e3779b1ull+v*0x85ebca6bull+w;
             stats.identity2+=u*v+w*w;
         });
#ifdef HOST_TRACE
    for(uint32_t x=0;x<job.length;++x) { host_trace(job.source_u,src[job.ordinal],target[x]); }
#endif
        uint32_t x=0;
        for(;x+4<=job.length;x+=4) {
            uint32_t keys[4],slots[4],values[4];
#pragma GCC unroll 4
            for(uint32_t z=0;z<4;z++) {
                uint32_t y=target[x+z]; keys[z]=y+1; slots[z]=hash_slot(y,job.mask); values[z]=hash[slots[z]];
            }
#pragma GCC unroll 4
            for(uint32_t z=0;z<4;z++) {
                uint32_t value=values[z],at=slots[z];
                while(value && value!=keys[z]) { at=(at+1)&job.mask; value=hash[at]; PROF(++stats.probes); }
                if(value==keys[z]) { ++count; }
            }
        }
        for(;x<job.length;x++) {
            uint32_t y=target[x],key=y+1,at=hash_slot(y,job.mask),value;
            while((value=hash[at]) && value!=key) { at=(at+1)&job.mask; PROF(++stats.probes); }
            if(value==key) { ++count; }
        }
#elif FAMILY == 2
    for(uint32_t k=job.path;k<job.ordinal;k++) {
        uint32_t key=src[k],lo=0,hi=job.length;
        PROF(++stats.candidates;
             stats.identity1+=(uint64_t(job.source_u)+1)*0x9e3779b1ull+(uint64_t(job.mask)+1)*0x85ebca6bull+k;
             stats.identity2+=(uint64_t(job.source_u)+1)*(uint64_t(job.mask)+1)+uint64_t(k)*k;);
        while(lo<hi) {
            uint32_t mid=(lo+hi)/2; PROF(++stats.probes);
            if(target[mid]==key) { ++count; break; }
            if(target[mid]<key) { lo=mid+1; } else { hi=mid; }
        }
    }
#elif FAMILY == 3
    const uint32_t* lr=src; const uint32_t* sr=target;
    uint32_t length=job.degree,slen=job.length;
    if(length<slen) { lr=target; sr=src; length=job.length; slen=job.degree; }
    if(length && slen && !(lr[0]>sr[slen-1] || lr[length-1]<sr[0])) {
        auto samples=hash+job.mask;
        for(uint32_t x=0;x<slen;x++) {
            uint32_t key=sr[x]; if(key<lr[0]) { continue; } if(key>lr[length-1]) { break; }
            PROF(++stats.candidates;
                 stats.identity1+=(uint64_t(job.ordinal)+1)*0x9e3779b1ull+x;
                 stats.identity2+=(uint64_t(job.source_u)+1)*(uint64_t(job.ordinal)+1)+uint64_t(x)*x;);
            uint32_t lo=0,hi=32; bool found=false;
            while(hi>lo+1) {
                uint32_t mid=(hi+lo)/2,y=samples[mid]; PROF(++stats.probes);
                if(y==key) { found=true; break; }
                if(y<key) { lo=mid; } else { hi=mid; }
            }
            if(!found) {
                uint32_t a=uint64_t(lo)*length/32,b=uint64_t(hi)*length/32;
                while(a<b) {
                    uint32_t mid=(a+b)/2; PROF(++stats.probes);
                    if(lr[mid]==key) { found=true; break; }
                    if(lr[mid]<key) { a=mid+1; } else { b=mid; }
                }
            }
            count+=found;
        }
    }
#endif
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

#ifndef TAIL_ON
#define TAIL_ON 1
#endif
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
    for(uint32_t j=0;j<384;j++) { tags[j]=0xffffffffu; }
    for(uint32_t j=0;j<HASH_SIZE;j++) { hash[j]=0; }
    uint32_t error=0,seq=0,nused=0;
    (void)sourcebuf; (void)used; (void)nused; (void)n; (void)tasks; (void)cache; (void)meta;
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
        if(b>a) { requests[which]+=(b-1)/PAGE_WORDS-a/PAGE_WORDS+1; }
#endif
#else
        uint32_t offset=which==0?0:(which==1?16384/PAGE_BYTES:81920/PAGE_BYTES),slots=(which==1?65536:16384)/PAGE_BYTES;
        uint32_t* out=dst+lo%16;
        for(uint64_t p=lo;p<hi;) {
            uint32_t page=p/PAGE_WORDS,slot=page%slots,at=offset+slot;
            if(tags[at]!=page) {
                read_page(which,page,(uintptr_t)(cache+at*PAGE_WORDS)); noc_async_read_barrier(); tags[at]=page;
                PROF(++misses[which]; ++requests[which]; bytes[which]+=PAGE_BYTES; ++barriers);
            }
            uint32_t take=PAGE_WORDS-p%PAGE_WORDS;
            if(take>hi-p) { take=hi-p; }
#if COUNTERS
            uint64_t copy_start=uint64_t(0);
#endif
            for(uint32_t j=0;j<take;j++) { out[j]=cache[at*PAGE_WORDS+p%PAGE_WORDS+j]; }
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

#if TAIL_ON
    const uint32_t threshold=n>65536?n-65536:0,tail_first=threshold&~15u;
    auto tail_header=(volatile uint32_t*)get_write_ptr(2);
    auto tail=(uint32_t*)(get_write_ptr(2)+64);
    if(CHANNEL==0) {
        row_range_16k(threshold,n+1,(uintptr_t)tail);
        noc_async_read_barrier();
        PROF(uint64_t hi=(uint64_t(n)+16)&~uint64_t(15);
             requests[0]+=(hi-1)/4096-tail_first/4096+1;
             bytes[0]+=(hi-tail_first)*4; ++barriers;);
         tail_header[0]=epoch;
    } else {
        while(tail_header[0]!=epoch) { invalidate_l1_cache(); }
        
    }
#endif
    auto metadata=[&](const uint32_t* ids,uint32_t cnt,Ref* dest) {
#if TAIL_ON
        auto mapping=(uint32_t*)(base+MAPPING)+128;
        auto packed=(uint32_t*)(base+MERGE);
        uint32_t size=plan_pairs(ids,cnt,threshold,mapping,[&](uint32_t lo,uint32_t hi,uint32_t offset) {
            if(offset+(hi-lo)*4>MERGE_BYTES) { error=30; return; }
            row_range_16k(lo,hi,(uintptr_t)packed+offset);
            PROF(requests[0]+=(hi-1)/4096-lo/4096+1; bytes[0]+=uint64_t(hi-lo)*4;);
        });
        if(size) { noc_async_read_barrier(); PROF(++barriers;); }
        if(size>MERGE_BYTES || error) { error=30; return; }
        for(uint32_t k=0;k<cnt;++k) {
            const auto pair=ids[k]>=threshold?tail+(ids[k]-tail_first):packed+mapping[k]/4;
            dest[k]={pair[0],pair[1],0,0};
            if(pair[1]<pair[0] || pair[1]-pair[0]+32>ARENA_WORDS) { error=4; }
        }
#else
        auto packed=(uint32_t*)(base+MERGE);
        for(uint32_t k=0;k<cnt;++k) {
            const uint32_t lo=ids[k],hi=lo+2;
            row_range_16k(lo,hi,(uintptr_t)(packed+k*32));
            PROF(uint64_t a=uint64_t(lo)&~uint64_t(15); uint64_t b=(uint64_t(hi)+15)&~uint64_t(15);
                 requests[0]+=(b-1)/4096-a/4096+1; bytes[0]+=(b-a)*4;);
        }
        if(cnt) { noc_async_read_barrier(); PROF(++barriers;); }
        for(uint32_t k=0;k<cnt;++k) {
            const auto pair=packed+k*32+ids[k]%16;
            dest[k]={pair[0],pair[1],0,0};
            if(pair[1]<pair[0] || pair[1]-pair[0]+32>ARENA_WORDS) { error=4; }
        }
#endif
    };
#if FAMILY == 4
    struct TrustContext { uint32_t u=0,a=0,degree=0,nused=0; };
    TrustContext contexts[SOURCE_CONTEXTS]; uint32_t last_sequence[SOURCE_CONTEXTS]={};
    uint64_t next_source=id;
#if SOURCE_CONTEXTS == 2
    auto second_hash=(uint32_t*)(base+HASH1);
    for(uint32_t j=0;j<HASH_SIZE;++j) { second_hash[j]=0; }
#endif
    auto prepare_next=[&](uint32_t bank)->bool {
        if(!wait_ack(last_sequence[bank],true)) { return false; }
        auto& c=contexts[bank];
        auto sb=(uint32_t*)(base+source_offset(bank));
        auto hb=(uint32_t*)(base+hash_offset(bank));
        auto ub=(uint32_t*)(base+used_offset(bank));
        while(next_source<n && !error) {
            PROF(sync[PHASE]=PREP_SOURCE);
            c.u=uint32_t(next_source); next_source+=cpu_engines;
            auto pair=fetch(0,c.u,c.u+2,pairs); barrier();
            c.a=pair[0]; c.degree=pair[1]-pair[0];
            if(pair[1]<pair[0]) { error=4; return false; }
            if(c.degree<2) { continue; }
            if(c.degree>SOURCE_CAP) { error=3; return false; }
            auto loaded=fetch(1,c.a,c.a+c.degree,sb); barrier();
            build_hash(loaded,c.degree,hb,ub,c.nused);
            PROF(++sources);
            return true;
        }
        return false;
    };
    uint32_t ctx=0; bool active=prepare_next(ctx);
    while(active && !error) {
        const auto c=contexts[ctx];
        const uint32_t u=c.u,degree=c.degree;
        auto src=(uint32_t*)(base+source_offset(ctx))+c.a%16;
        hash=(uint32_t*)(base+hash_offset(ctx));
        bool next_prepared=false,next_attempted=false;
        [[maybe_unused]] uint32_t source_batches=0;
        for(uint32_t t0=0;t0+1<degree && !error;t0+=BATCH) {
            uint32_t cnt=degree-1-t0; if(cnt>BATCH) { cnt=BATCH; }
            PROF(sync[PHASE]=FETCH_TARGET);
            metadata(src+t0,cnt,refs);
            for(uint32_t k=0;k<cnt && !error;) {
                if(seq>=0xfffffffeu) { error=5; break; }
                uint32_t next=seq+1,arena=(next-1)%2,off=slot_offset(next);
                if(next>2 && !wait_ack(next-2,false)) { break; }
                auto jobs=(Job*)(base+JOBS)+arena*BATCH;
                uint32_t k1=plan(refs,k,cnt,jobs,u,degree,c.a%16,t0);
                if(k1==k) { error=6; break; }
                auto target=(uint32_t*)(base+TARGET)+arena*ARENA_WORDS;
                for(uint32_t j=k;j<k1;++j) {
                    if(refs[j].hi>refs[j].lo) { fetch(1,refs[j].lo,refs[j].hi,target+jobs[j-k].target_offset-refs[j].lo%16); }
                }
                barrier();
                const uint32_t maxkey=src[degree-1];
                for(uint32_t j=0;j<k1-k;++j) {
                    auto& job=jobs[j]; const auto row=target+job.target_offset;
                    uint32_t cap=job.length;
                    if(cap && row[cap-1]>maxkey) {
                        uint32_t lo=0,hi=cap;
                        while(lo<hi) { uint32_t mid=lo+(hi-lo)/2; if(row[mid]<=maxkey) { lo=mid+1; } else { hi=mid; } }
                        cap=lo;
                    }
                    job.length=cap; job.path=1;
                }
#if STRESS
                if(CHANNEL==0 && next%3==0) {
                    for(volatile uint32_t delay=0;delay<STRESS;++delay) { asm volatile("nop"); }
                }
#endif
                uint32_t batch=k1-k;
                sync[off+1]=u; sync[off+2]=batch; sync[off+3]=arena; sync[off+4]=ctx;
                 sync[off]=next; seq=next; last_sequence[ctx]=seq;
#if TRISC_ON
                for(uint32_t worker=0;worker<3;++worker) {
                    ProbeStats worker_stats; uint64_t worker_count=0;
                    for(uint32_t j=worker;j<batch;j+=4) {
                        worker_count+=probe(jobs[j],src,hash,target+jobs[j].target_offset,worker_stats);
                    }
                    const uint32_t at=WORKER+worker*32;
                    put64(sync,at,get64(sync,at)+worker_count);
                    put64(sync,at+2,get64(sync,at+2)+worker_stats.candidates);
                    put64(sync,at+4,get64(sync,at+4)+worker_stats.probes);
                    put64(sync,at+22,get64(sync,at+22)+worker_stats.identity1);
                    put64(sync,at+24,get64(sync,at+24)+worker_stats.identity2);
                }
#endif

                PROF(++batches; put64(result,224+batch*2,get64(result,224+batch*2)+1); sync[PHASE]=COMPUTE);
                ++source_batches;
                for(uint32_t j=(TRISC_ON?3:0);j<batch;j+=(TRISC_ON?4:1)) {
                    owncount+=probe(jobs[j],src,hash,target+jobs[j].target_offset,stats);
                }
                k=k1;
#if SOURCE_CONTEXTS == 2
                if(!next_attempted) { next_attempted=true; next_prepared=prepare_next(ctx^1u); }
#endif
            }
        }
        PROF(put64(result,128+source_bin(source_batches)*2,get64(result,128+source_bin(source_batches)*2)+1));
#if SOURCE_CONTEXTS == 2
        if(!next_attempted) { next_prepared=prepare_next(ctx^1u); }
        active=next_prepared; ctx^=1u;
#else
        (void)next_attempted; (void)next_prepared;
        if(!wait_ack(seq,true)) { break; }
        active=prepare_next(ctx);
#endif
    }
#elif FAMILY == 1
#if SOURCE_CONTEXTS == 2
    struct SourceContext { uint32_t u=0,first=0,last=0,a=0,degree=0,nused=0; };
    SourceContext contexts[2]; uint32_t last_sequence[2]={0,0};
    uint64_t next_source=id;
    auto hash1=(uint32_t*)(base+HASH1);
    for(uint32_t j=0;j<HASH_SIZE;++j) { hash1[j]=0; }
    auto prepare_next=[&](uint32_t bank)->bool {
        // Retire all readers before clearing or overwriting this bank.
        if(!wait_ack(last_sequence[bank],true)) { return false; }
        auto& c=contexts[bank];
        auto sb=(uint32_t*)(base+source_offset(bank));
        auto hb=(uint32_t*)(base+hash_offset(bank));
        auto ub=(uint32_t*)(base+used_offset(bank));
        while(next_source<n && !error) {
            PROF(sync[PHASE]=PREP_SOURCE);
#if COUNTERS
            uint64_t source_start=uint64_t(0);
#endif
            c.u=uint32_t(next_source);next_source+=cpu_engines;
            fetch(2,c.u,c.u+2,pairs);fetch(0,c.u,c.u+2,pairs+32);barrier();
            c.first=pairs[c.u%16];c.last=pairs[c.u%16+1];
            if(c.first==c.last) { PROF(source_ticks+=uint64_t(0)-source_start);continue; }
            c.a=pairs[32+c.u%16];c.degree=pairs[33+c.u%16]-c.a;
            if(c.degree>SOURCE_CAP || !c.degree) { error=3;return false; }
            auto loaded=fetch(1,c.a,c.a+c.degree,sb);barrier();
            if(c.degree>128) { build_hash(loaded,c.degree,hb,ub,c.nused); }
            PROF(++sources;source_ticks+=uint64_t(0)-source_start);
            return true;
        }
        return false;
    };
    uint32_t ctx=0;bool active=prepare_next(ctx);
    while(active && !error) {
        const auto c=contexts[ctx];
        const uint32_t u=c.u,first=c.first,last=c.last,a=c.a,degree=c.degree;
        auto src=(uint32_t*)(base+source_offset(ctx))+a%16;
        hash=(uint32_t*)(base+hash_offset(ctx));
        bool next_prepared=false,next_attempted=false;
        [[maybe_unused]] uint32_t source_batches=0;
        for(uint32_t t0=first;t0<last && !error;t0+=BATCH) {
            PROF(sync[PHASE]=FETCH_TARGET);
#if COUNTERS
            uint64_t target_start=uint64_t(0);
#endif
            uint32_t cnt=last-t0; if(cnt>BATCH) { cnt=BATCH; }
            fetch(2,uint64_t(n)+1+t0,uint64_t(n)+1+t0+cnt,tasks);
            barrier();
            metadata(tasks+(uint64_t(n)+1+t0)%16,cnt,refs);
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
                sync[off+1]=u; sync[off+2]=batch; sync[off+3]=arena; sync[off+4]=ctx;
                 sync[off]=next; seq=next; last_sequence[ctx]=seq;
#if TRISC_ON
                for(uint32_t worker=0;worker<3;++worker) {
                    ProbeStats worker_stats; uint64_t worker_count=0;
                    for(uint32_t j=worker;j<batch;j+=4) {
                        worker_count+=probe(jobs[j],src,hash,target+jobs[j].target_offset,worker_stats);
                    }
                    const uint32_t at=WORKER+worker*32;
                    put64(sync,at,get64(sync,at)+worker_count);
                    put64(sync,at+2,get64(sync,at+2)+worker_stats.candidates);
                    put64(sync,at+4,get64(sync,at+4)+worker_stats.probes);
                    put64(sync,at+22,get64(sync,at+22)+worker_stats.identity1);
                    put64(sync,at+24,get64(sync,at+24)+worker_stats.identity2);
                }
#endif

                PROF(++batches; put64(result,224+batch*2,get64(result,224+batch*2)+1); sync[PHASE]=COMPUTE);
                ++source_batches;
                for(uint32_t j=(TRISC_ON?3:0);j<batch;j+=(TRISC_ON?4:1)) {
                    owncount+=probe(jobs[j],src,hash,target+jobs[j].target_offset,stats);
                }
                k=k1;
                // The published slot owns its source bank until all three ACKs.
                // Prepare once after the first batch, while workers consume it.
                if(!next_attempted) {
                    next_attempted=true;next_prepared=prepare_next(ctx^1u);
                }
            }
        }
        PROF(put64(result,128+source_bin(source_batches)*2,get64(result,128+source_bin(source_batches)*2)+1));
        if(!next_attempted) { next_prepared=prepare_next(ctx^1u); }
        active=next_prepared;ctx^=1u;
    }
    // Final drain also covers the previous slot; workers consume each channel in order.
    if(!error) { wait_ack(seq,true); }
#else
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
        if(degree>128) { build_hash(src,degree,hash,used,nused); }
        PROF(++sources; source_ticks+=uint64_t(0)-source_start);
        [[maybe_unused]] uint32_t source_batches=0;
        for(uint32_t t0=first;t0<last && !error;t0+=BATCH) {
            PROF(sync[PHASE]=FETCH_TARGET);
#if COUNTERS
            uint64_t target_start=uint64_t(0);
#endif
            uint32_t cnt=last-t0; if(cnt>BATCH) { cnt=BATCH; }
            fetch(2,uint64_t(n)+1+t0,uint64_t(n)+1+t0+cnt,tasks);
            barrier();
            metadata(tasks+(uint64_t(n)+1+t0)%16,cnt,refs);
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
#endif
#else
    [[maybe_unused]] uint32_t source_batches=0;
    auto publish=[&](uint32_t u,uint32_t degree,uint32_t source_offset,const uint32_t* src,uint32_t cnt) {
        for(uint32_t k=0;k<cnt && !error;) {
            if(seq>=0xfffffffeu) { error=5; break; }
            uint32_t next=seq+1,arena=(next-1)%2,off=slot_offset(next);
            if(next>2 && !wait_ack(next-2,false)) { break; }
            auto jobs=(Job*)(base+JOBS)+arena*BATCH;
            uint32_t k1=plan(refs,k,cnt,jobs,u,degree,source_offset,0);
            if(k1==k) { error=6; break; }
            auto target=(uint32_t*)(base+TARGET)+arena*ARENA_WORDS;
            for(uint32_t j=k;j<k1;j++) {
#if FAMILY == 2
                jobs[j-k].path=used[j]; jobs[j-k].ordinal=used[BATCH+j]; jobs[j-k].mask=used[2*BATCH+j];
#else
                jobs[j-k].path=0; jobs[j-k].ordinal=used[3*BATCH+j]; jobs[j-k].mask=arena*BATCH*32+(j-k)*32;
#endif
                if(refs[j].hi>refs[j].lo) { fetch(1,refs[j].lo,refs[j].hi,target+jobs[j-k].target_offset-refs[j].lo%16); }
            }
            barrier();
#if FAMILY == 3
            for(uint32_t j=k;j<k1;j++) {
                auto& job=jobs[j-k]; auto row=src; uint32_t length=degree;
                if(length<job.length) { row=target+job.target_offset; length=job.length; }
                auto samples=hash+job.mask;
                for(uint32_t z=0;z<32;z++) { samples[z]=(row==src)?used[1024+z]:(length?row[uint64_t(z)*length/32]:0); }
            }
#endif
            uint32_t batch=k1-k; sync[off+1]=u; sync[off+2]=batch; sync[off+3]=arena;
             sync[off]=next; seq=next;
            PROF(++batches; put64(result,224+batch*2,get64(result,224+batch*2)+1););
            ++source_batches;
            for(uint32_t j=(TRISC_ON?3:0);j<batch;j+=(TRISC_ON?4:1)) {
                owncount+=probe(jobs[j],src,hash,target+jobs[j].target_offset,stats);
            }
            k=k1;
        }
    };
    auto rowpair=[&](uint32_t u,uint32_t& lo,uint32_t& hi) {
        auto ptr=fetch(0,u,u+2,pairs); barrier(); lo=ptr[0]; hi=ptr[1];
    };
#if FAMILY == 2
    auto pref=[&](uint32_t u)->uint64_t {
        auto ptr=fetch(2,uint64_t(u)*2,uint64_t(u)*2+2,pairs+32); barrier();
        return uint64_t(ptr[0])+(uint64_t(ptr[1])<<32);
    };
    auto wedge_start=[](uint32_t d,uint32_t j)->uint64_t { return uint64_t(j)*(2*uint64_t(d)-j-1)/2; };
    uint64_t wedge_total=pref(n); uint32_t held_u=0xffffffffu;
    const uint32_t* src=sourcebuf;
    for(uint64_t start=uint64_t(id)*127;start<wedge_total && !error;start+=uint64_t(cpu_engines)*127) {
        uint32_t lo=0,hi=n;
        while(lo<hi) { uint32_t mid=(lo+hi)/2; if(pref(mid+1)<=start) { lo=mid+1; } else { hi=mid; } }
        uint32_t u=lo,first,last; rowpair(u,first,last); uint32_t degree=last-first;
        uint64_t index=start-pref(u); uint32_t l=0,r=degree-1;
        while(l+1<r) { uint32_t mid=(l+r)/2; if(wedge_start(degree,mid)<=index) { l=mid; } else { r=mid; } }
        uint32_t j=l,k=uint32_t(index-wedge_start(degree,j))+j+1;
        uint64_t q=start,stop=start+127; if(stop>wedge_total) { stop=wedge_total; }
        while(q<stop && !error) {
            if(degree>SOURCE_CAP) { error=3; break; }
            uint32_t cnt=0;
            while(q<stop && cnt<BATCH && j+1<degree) {
                uint64_t take=degree-k; if(take>stop-q) { take=stop-q; }
                used[cnt]=k; used[BATCH+cnt]=k+uint32_t(take); used[2*BATCH+cnt]=j; ++cnt;
                q+=take; k+=uint32_t(take); if(k>=degree) { ++j; k=j+1; }
            }
            if(!cnt) { error=7; break; }
            if(held_u!=u) {
                if(!wait_ack(seq,true)) { break; }
                src=fetch(1,first,last,sourcebuf); held_u=u; PROF(++sources;); source_batches=0;
            }
            barrier();
            auto ids=(uint32_t*)(base+MAPPING);
            for(uint32_t t=0;t<cnt;++t) { ids[t]=src[used[2*BATCH+t]]; }
            metadata(ids,cnt,refs);
            publish(u,degree,first%16,src,cnt);
            if(q<stop && j+1>=degree) {
                do { ++u; rowpair(u,first,last); degree=last-first; } while(degree<2);
                j=0;k=1;
            }
        }
    }
#else
    const uint32_t m=get_common_arg_val<uint32_t>(3);
    uint32_t held_u=0xffffffffu,first_u=0,last_u=0; const uint32_t* src=sourcebuf;
    for(uint64_t edge=uint64_t(id)*32;edge<m && !error;edge+=uint64_t(cpu_engines)*32) {
        uint32_t cnt=uint32_t(m-edge); if(cnt>32) { cnt=32; }
        auto su=fetch(2,edge,edge+cnt,tasks);
        auto ids=fetch(1,edge,edge+cnt,(uint32_t*)(base+MAPPING)); barrier();
        auto edge_refs=(Ref*)meta;
        metadata(ids,cnt,edge_refs);
        uint32_t p=0;
        while(p<cnt && !error) {
            uint32_t u=su[p],end=p+1; while(end<cnt && su[end]==u) { ++end; }
            if(held_u!=u) {
                if(!wait_ack(seq,true)) { break; }
                rowpair(u,first_u,last_u); uint32_t degree=last_u-first_u;
                if(degree>SOURCE_CAP) { error=3; break; }
                src=fetch(1,first_u,last_u,sourcebuf); barrier();
                for(uint32_t z=0;z<32;z++) { used[1024+z]=degree?src[uint64_t(z)*degree/32]:0; }
                held_u=u; source_batches=0; PROF(++sources;);
            }
            for(uint32_t j=p;j<end;j++) {
                refs[j-p]=edge_refs[j]; used[3*BATCH+j-p]=uint32_t(edge+j);
                if(refs[j-p].hi<refs[j-p].lo || refs[j-p].hi-refs[j-p].lo+32>ARENA_WORDS) { error=4; }
            }
            publish(u,last_u-first_u,first_u%16,src,end-p);p=end;
        }
    }
    PROF(put64(result,128+source_bin(source_batches)*2,get64(result,128+source_bin(source_batches)*2)+1););
#endif
#endif
    if(!error) { wait_ack(seq,true); }
    sync[ERROR]=error; PROF(sync[PHASE]=FINISHED);
     sync[EOF_SEQ]=seq+1;
    uint64_t total=owncount,candidates=stats.candidates,probes=stats.probes;
    (void)candidates; (void)probes;
#if COUNTERS
    uint64_t identity1=stats.identity1,identity2=stats.identity2;
#endif
    for(uint32_t w=0;w<3;w++) {
        uint32_t at=WORKER+w*32; total+=get64(sync,at); error|=sync[at+6];
        PROF(identity1+=get64(sync,at+22); identity2+=get64(sync,at+24); candidates+=get64(sync,at+2); probes+=get64(sync,at+4);
             put64(result,34+w*2,get64(sync,at+2));
             for(uint32_t j=0;j<6;j++) { put64(result,64+w*16+j*2,get64(sync,at+8+j*2)); });
    }
    put64(result,0,total);
    PROF(put64(result,2,sources); put64(result,4,candidates); put64(result,6,probes);
         for(uint32_t j=0;j<3;j++) { put64(result,8+j*2,misses[j]); put64(result,360+j*2,requests[j]); put64(result,366+j*2,bytes[j]); }
         put64(result,32,stats.candidates); put64(result,40,ack_slot); put64(result,42,ack_source);
         put64(result,44,source_ticks); put64(result,46,target_ticks); put64(result,48,copy_ticks);
         put64(result,50,uint64_t(0)-started); put64(result,52,batches); put64(result,54,barriers);
         put64(result,56,stats.high_candidates); put64(result,400,identity1); put64(result,402,identity2));
    result[22]=error; result[24]=id; result[25]=0x53545243;
    noc_async_write_tile(id,output,(uintptr_t)result); noc_async_write_barrier();
}
