#pragma GCC diagnostic ignored "-Wmisleading-indentation"
#include <stdint.h>
#ifdef DATA_WORKER
#include "api/dataflow/dataflow_api.h"
#define REFRESH() invalidate_l1_cache()
#else
#include "api/compute/compute_kernel_api.h"
#include "api/compute/common.h"
#define REFRESH() asm volatile("fence" ::: "memory")
#endif
static inline uint32_t avalanche(uint32_t x){x^=x>>16;x*=0x7feb352d;x^=x>>15;x*=0x846ca68b;return x^(x>>16);}
static inline uint32_t hash_slot(uint32_t x,uint32_t mask){return HASH_MIX==2?(uint32_t(x*0x9E3779B1u)>>__builtin_clz(mask)):((HASH_MIX==1?avalanche(x):(x^(x>>16)))&mask);}
#if HIST_BINS
static inline uint32_t label_of(uint32_t x){return (x^(x>>16))%LABELS;}
#endif
#if PROFILE
#define HASH_COUNT(x) ++(x)
#else
#define HASH_COUNT(x)
#endif
void kernel_main(){
 #if PROFILE
 uint64_t lookup_collision_steps=0;
 #endif
 const uint32_t worker=COMPILE_FOR_TRISC;
 uint32_t bases[2]={get_common_arg_val<uint32_t>(0),get_common_arg_val<uint32_t>(1)},epoch=get_common_arg_val<uint32_t>(5);
#if HIST_BINS
 auto hist=(uint64_t*)get_common_arg_val<uint32_t>(HIST_BASE_ARG)+HIST_BINS*(2+worker);
 for(uint32_t i=0;i<HIST_BINS;i++)hist[i]=0;
#endif
 auto s0=(volatile uint32_t*)bases[0];auto s1=(volatile uint32_t*)bases[1];
 uint64_t count=0;uint32_t steps[2]={1,1},error=0,spin=0,preferred=0;
 do{REFRESH();}while((s0[0]!=epoch || s1[0]!=epoch) && ++spin<SPIN_CAP);
 if(s0[0]!=epoch || s1[0]!=epoch)error=32;
 while(!error){
  uint32_t channel=2;spin=0;
  while(channel==2){
   REFRESH();for(uint32_t choice=0;choice<2;choice++){uint32_t ch=preferred^choice;auto sy=ch?s1:s0;uint32_t off=16+((steps[ch]-1)%RING_SLOTS)*16;if(!sy[1] && sy[off]==steps[ch]){channel=ch;break;}}
   if(channel<2)break;if(s0[1]&&s1[1])break;if(++spin==SPIN_CAP){error=64;break;}
  }
  if(channel==2)break;preferred=channel^1;uint32_t base=bases[channel],step=steps[channel],off=16+((step-1)%RING_SLOTS)*16;auto sync=channel?s1:s0;
  REFRESH();uint32_t batch=sync[off+2],arena=sync[off+11];
  auto targets=(const uint32_t*)(base+TARGET_OFFSET);
  auto desc=(const uint32_t*)(base+JOBS_OFFSET)+arena*BATCH*8;
  const bool sharing=(epoch&(1u<<26)) && batch<GROUP;
  for(uint32_t group=0;group<(NO_TRISC?0u:batch);group+=(sharing?1:GROUP)){
   for(uint32_t lane=0;lane<(sharing?1:CONSUMER_SLOTS);lane++){uint32_t k=sharing?group:group+worker*CONSUMER_SLOTS+lane;if(k>=batch)break;
   auto d=desc+k*8;uint32_t ctx=d[0],j=d[1],cap=d[2],degree=d[4],mask=d[6];
   auto s=(const uint32_t*)(base+SOURCE_OFFSET)+ctx*SOURCE_CAP+d[5];
   auto hash=(const uint32_t*)(base+HASH_OFFSET)+ctx*HASH_SIZE;
   auto t=targets+arena*ARENA_WORDS+d[3];uint32_t c=0,a=0;
#if HIST_BINS
   const uint32_t hist_prefix=d[7];
#endif
   uint32_t from=d[1];
#if BOUND_TARGET
   // Sorted rows: keys above the largest source neighbor cannot close a triangle.
   if(cap&&t[cap-1]>s[degree-1]){
    uint32_t l=0,h=cap,maximum=s[degree-1];
    while(l<h){uint32_t mid=l+(h-l)/2;if(t[mid]<=maximum)l=mid+1;else h=mid;}cap=l;
   }
#endif
#if HYBRID_FACTOR
   const bool use_binary=(degree-from)*HYBRID_FACTOR<cap;
#else
   const bool use_binary=false;
#endif
   // A small batch cannot occupy one task per processor. Share its existing
   // payload, partitioning the same candidate side as the original lookup.
   if(sharing){
    const uint32_t rank=worker;
    if(use_binary){uint32_t first=from,nkeys=degree-from;from=first+nkeys*rank/GROUP;degree=first+nkeys*(rank+1)/GROUP;}
    else{uint32_t first=cap*rank/GROUP,last=cap*(rank+1)/GROUP;t+=first;cap=last-first;}
   }
#if HYBRID_FACTOR
   // For a short source suffix, search it in the fetched target CSR instead.
   if(use_binary){
    uint32_t lower=0;
    for(uint32_t z=from;z<degree;z++){
     uint32_t key=s[z],l=lower,h=cap;
     while(l<h){uint32_t mid=l+(h-l)/2;if(t[mid]<key)l=mid+1;else h=mid;}
     if(l<cap&&t[l]==key){++c;
#if HIST_BINS
      ++hist[hist_prefix+label_of(key)];
#endif
     }lower=l;
    }
   }else
#endif
   {

#if LOOKUP_WIDTH > 1
   for(;a+LOOKUP_WIDTH<=cap;a+=LOOKUP_WIDTH){
    uint32_t keys[LOOKUP_WIDTH],slots[LOOKUP_WIDTH],values[LOOKUP_WIDTH];
#pragma GCC unroll 8
    for(uint32_t z=0;z<LOOKUP_WIDTH;z++){uint32_t y=t[a+z];keys[z]=y+1;slots[z]=hash_slot(y,mask);values[z]=hash[slots[z]];}
#pragma GCC unroll 8
    for(uint32_t z=0;z<LOOKUP_WIDTH;z++){uint32_t x=values[z],slot=slots[z];while(x&&x!=keys[z]){slot=(slot+1)&mask;x=hash[slot];HASH_COUNT(lookup_collision_steps);}if(x==keys[z]){++c;
#if HIST_BINS
     ++hist[hist_prefix+label_of(keys[z]-1)];
#endif
    }}
   }
#endif
   for(;a<cap;a++){uint32_t y=t[a],key=y+1,slot=hash_slot(y,mask),x;while((x=hash[slot])&&x!=key){slot=(slot+1)&mask;HASH_COUNT(lookup_collision_steps);}if(x==key){++c;
#if HIST_BINS
    ++hist[hist_prefix+label_of(y)];
#endif
   }}
   }
   count+=c;
   }
  }
  asm volatile("fence" ::: "memory");sync[off+8+worker]=step;steps[channel]++;
 }
 #if PROFILE
 s0[132+worker*8]=lookup_collision_steps;s0[133+worker*8]=lookup_collision_steps>>32;
 #endif
 s0[128+worker*8]=count;s0[129+worker*8]=count>>32;s0[130+worker*8]=error;asm volatile("fence" ::: "memory");s0[131+worker*8]=epoch;
}
