#pragma GCC diagnostic ignored "-Wmisleading-indentation"
#include <stdint.h>
// METADATA_PLAN_HEADER
#include "api/dataflow/dataflow_api.h"
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
 uint64_t lookup_collision_steps=0,hash_insert_collisions=0;
 uint64_t effective_probe_candidates=0;
 #endif
 const uint32_t gx=get_common_arg_val<uint32_t>(3),nc=get_common_arg_val<uint32_t>(4),epoch=get_common_arg_val<uint32_t>(5);
 const uint32_t begin=get_common_arg_val<uint32_t>(6),end=get_common_arg_val<uint32_t>(7),mod=get_common_arg_val<uint32_t>(8),rem=get_common_arg_val<uint32_t>(9);
 const uint32_t cid=get_absolute_logical_y()*gx+get_absolute_logical_x();
 uint64_t io_requests[3]={},io_bytes[3]={},io_barriers=0;
 // GENERATED_ACCESSORS
 const uint32_t base=get_write_ptr(CHANNEL);auto sync=(volatile uint32_t*)base;
#if HIST_BINS
 auto hist=(uint64_t*)get_common_arg_val<uint32_t>(HIST_BASE_ARG)+HIST_BINS*CHANNEL;
 for(uint32_t i=0;i<HIST_BINS;i++)hist[i]=0;
#endif
 auto targets=(uint32_t*)(base+TARGET_OFFSET);auto result=(uint32_t*)(base+RESULT_OFFSET);
 for(uint32_t i=0;i<192;i++)sync[i]=0;
 for(uint32_t i=0;i<CONTEXTS*HASH_SIZE;i++)((uint32_t*)(base+HASH_OFFSET))[i]=0;
 asm volatile("fence" ::: "memory");sync[0]=epoch;
 uint64_t sources=0,owncount=0,candidates=0,tiles=0,target_bytes=0,meta_requests=0;uint32_t step=0,error=0,maxdegree=0,active=0;uint32_t usedcount[CONTEXTS]={},laststep[CONTEXTS]={},arena_last[2*CONTEXTS]={};
 auto wait=[&](uint32_t seq)->bool{
  if(!seq)return true;uint32_t off=16+((seq-1)%RING_SLOTS)*16,spins=0;
  while(true){invalidate_l1_cache();bool okay=true;for(uint32_t w=0;w<3;w++)okay &= sync[off+8+w]>=seq;if(okay)return true;if(++spins==SPIN_CAP)return false;}
 };
 // A source tile owns closing vertices; target segments partition each target row.
 uint64_t source_seq=cid*2+CHANNEL;
 uint32_t uf=0,ud=0,tile_begin=0,source_u=0,target_v=0;
 uint32_t ctx=0,degree=0,source_offset=0,limit=0,vpos=0;
 uint32_t stage_count=0,stage_index=0,target_lo=0,target_hi=0,target_from=0;
 uint32_t promoted=0;
 bool eof=false,tile_ready=false,pooled=false;
 uint32_t tile_hash_mask=HASH_SIZE-1;
 auto staging=(uint32_t*)(base+STAGE_OFFSET);
 #if AUX_ROWPTR || (!TAIL_MERGE && !PIPE_META)
 auto vids=staging+META_STAGE*32;
 auto stage_ids=[&]()->uint32_t*{
  if(vpos>=tile_begin && vpos+stage_count<=tile_begin+degree)
   return (uint32_t*)(base+SOURCE_OFFSET)+ctx*SOURCE_CAP+source_offset+(vpos-tile_begin);
  return vids+(uf+vpos)%16;
 };
#endif
#if AUX_ROWPTR
 auto auxmeta=(uint32_t*)(base+AUX_OFFSET);
 uint32_t aux_word_offset=0;
 auto begin_stage=[&](){
  stage_count=limit-vpos;
  if(stage_count>META_STAGE){stage_count=META_STAGE;}
  stage_index=0;
  if(PROFILE){meta_requests+=stage_count;}
  auto ids=stage_ids();
  for(uint32_t k=0;k<stage_count;k++){
   staging[k*32]=auxmeta[aux_word_offset+2*(vpos+k)];
   staging[k*32+1]=auxmeta[aux_word_offset+2*(vpos+k)+1];
   staging[k*32+2]=ids[k];
  }
 };
 auto finish_stage=[&](){};
#elif !TAIL_MERGE && !PIPE_META
 auto begin_stage=[&](){
  stage_count=limit-vpos;if(stage_count>META_STAGE)stage_count=META_STAGE;stage_index=0;
  if(!(vpos>=tile_begin && vpos+stage_count<=tile_begin+degree)){
   uint32_t lo=uf+vpos;read_col_range(lo,lo+stage_count,(uint32_t)vids);noc_async_read_barrier();if(PROFILE){++io_barriers;}
  }
  if(PROFILE)meta_requests+=stage_count;
  auto ids=stage_ids();
  for(uint32_t k=0;k<stage_count;k++){uint32_t v=ids[k];read_row_range(v,v+2,(uint32_t)(staging+k*32));}
 };
 auto finish_stage=[&](){
  noc_async_read_barrier();if(PROFILE){++io_barriers;}auto ids=stage_ids();
  for(uint32_t k=0;k<stage_count;k++){auto pair=staging+k*32+ids[k]%16;uint32_t a=pair[0],b=pair[1];staging[k*32]=a;staging[k*32+1]=b;staging[k*32+2]=ids[k];}
 };
#else
 uint32_t metadata_bank=0;
 uint32_t slot_start[2]={},slot_count[2]={};
 bool slot_valid[2]={},slot_wait[2]={};
 auto stage_buffer=[&](uint32_t b)->uint32_t*{
  return (uint32_t*)(base+(b?STAGE2_OFFSET:STAGE_OFFSET));
 };
 const uint32_t tail_threshold=end>(65536u)?end-65536u:0u;
 const uint32_t tail_first=tail_threshold&~15u;
 uint32_t tail_data=0;
#if TAIL_MERGE
 const uint32_t shared=get_write_ptr(2);
 auto ready=(volatile uint32_t*)shared;
 tail_data=shared+64u;
 if(CHANNEL==0){
  read_row_range(tail_threshold,end+1u,tail_data);
  noc_async_read_barrier();if(PROFILE){++io_barriers;}
  asm volatile("fence" ::: "memory");ready[0]=epoch;
 }else{
  while(ready[0]!=epoch){invalidate_l1_cache();}
  asm volatile("fence" ::: "memory");
 }
#endif
 auto issue_stage=[&](uint32_t b,uint32_t start){
  uint32_t count=limit-start;if(count>META_STAGE){count=META_STAGE;}
  auto buf=stage_buffer(b);auto ids=buf+META_STAGE*32;
  auto src=(uint32_t*)(base+SOURCE_OFFSET)+ctx*SOURCE_CAP+source_offset;
  // Copy IDs before source-bank promotion/reuse. Inputs fit one pooled source tile.
  for(uint32_t k=0;k<count;++k){ids[k]=src[start-tile_begin+k];}
  slot_start[b]=start;slot_count[b]=count;slot_valid[b]=true;
  if(PROFILE){meta_requests+=count;}
#if TAIL_MERGE
  const uint32_t raw=base+MERGE_OFFSET+b*MERGE_BYTES;
  uint32_t bytes=plan_metadata(ids,count,tail_threshold,buf+3,32,
   [&](uint32_t lo,uint32_t hi,uint32_t offset){read_row_range(lo,hi,raw+offset);});
  slot_wait[b]=bytes!=0;
#else
  slot_wait[b]=true;
  for(uint32_t k=0;k<count;++k){read_row_range(ids[k],ids[k]+2u,(uint32_t)(buf+k*32));}
#endif
 };
 auto begin_stage=[&](){
  if(PIPE_META && slot_valid[metadata_bank^1u] && slot_start[metadata_bank^1u]==vpos){metadata_bank^=1u;}
  if(!slot_valid[metadata_bank] || slot_start[metadata_bank]!=vpos){issue_stage(metadata_bank,vpos);}
  staging=stage_buffer(metadata_bank);stage_count=slot_count[metadata_bank];stage_index=0;
 };
 auto finish_stage=[&](){
  const uint32_t b=metadata_bank;auto ids=staging+META_STAGE*32;
  if(slot_wait[b]){noc_async_read_barrier();if(PROFILE){++io_barriers;}}
  for(uint32_t k=0;k<stage_count;++k){
   const uint32_t v=ids[k];uint32_t a,z;
#if TAIL_MERGE
   auto pair=(uint32_t*)(v>=tail_threshold?tail_data+(v-tail_first)*4u:base+MERGE_OFFSET+b*MERGE_BYTES+staging[k*32+3]);
#else
   auto pair=staging+k*32+v%16u;
#endif
   a=pair[0];z=pair[1];staging[k*32]=a;staging[k*32+1]=z;staging[k*32+2]=v;
  }
  slot_valid[b]=false;
  const uint32_t next=slot_start[b]+stage_count;
  if(PIPE_META && next<limit){issue_stage(b^1u,next);}
 };

#endif
 auto prepare_tile=[&](uint32_t bank)->bool{
#if !AUX_ROWPTR && (TAIL_MERGE || PIPE_META)
  metadata_bank=0;slot_valid[0]=slot_valid[1]=false;staging=stage_buffer(0);
#endif
  if(tile_begin>=ud){
   while(true){
    uint64_t u64=uint64_t(begin)+rem+source_seq*mod;source_seq+=nc*2;
    if(u64>=end){eof=true;return false;}uint32_t u=u64;source_u=u;
    read_row_range(u,u+2,(uint32_t)staging);noc_async_read_barrier();if(PROFILE){++io_barriers;}
    uf=staging[u%16];ud=staging[u%16+1]-uf;tile_begin=0;
    if(ud>=2)break;
   }
   if(PROFILE)++sources;if(PROFILE && ud>maxdegree){maxdegree=ud;}
  }
  const bool want_pool=POOL_BANKS && (epoch&(1u<<30)) && ud>SOURCE_CAP-16;
  // Reinterpret adjacent allocations only when every prior reader has retired.
  if(want_pool || pooled){
   if(!wait(step)){error=17;return false;}
   for(uint32_t b=0;b<CONTEXTS;b++){
    auto oldhash=(uint32_t*)(base+HASH_OFFSET)+b*HASH_SIZE;
    auto oldused=(uint32_t*)(base+USED_OFFSET)+b*SOURCE_CAP;
    for(uint32_t k=0;k<usedcount[b];k++)oldhash[oldused[k]]=0;
    usedcount[b]=0;
   }
   pooled=want_pool;
   if(pooled){bank=0;ctx=0;}
  }
  const uint32_t tile_capacity=(pooled?2u:1u)*(SOURCE_CAP-16);
  tile_hash_mask=(pooled?2*HASH_SIZE:HASH_SIZE)-1;
  // Controlled diagnostic: retain one wide bank and its allocation, but use
  // the original 16K hash address space for rows fitting the default 8208 tile.
  if((epoch&(1u<<29)) && HASH_SIZE==32768 && ud<=8208) tile_hash_mask=16383;
  degree=ud-tile_begin;
  if(degree>tile_capacity)degree=(epoch&(1u<<27))?1+(degree-1)%tile_capacity:tile_capacity;
  uint32_t first=uf+tile_begin;source_offset=first%16;
  auto source=(uint32_t*)(base+SOURCE_OFFSET)+bank*SOURCE_CAP;
  auto hash=(uint32_t*)(base+HASH_OFFSET)+bank*HASH_SIZE;
  auto used=(uint32_t*)(base+USED_OFFSET)+bank*SOURCE_CAP;
  read_col_range(first,first+degree,(uint32_t)source);
#if AUX_ROWPTR
  // Prepared inputs fit the existing single (possibly pooled) source tile.
  // Only the producer reads this buffer; consumers retain original source/target ownership.
  if(tile_begin!=0 || degree!=ud){error=22;return false;}
  aux_word_offset=(2ull*first)%16;
  read_aux_range(2ull*first,2ull*(first+degree),(uint32_t)auxmeta);
#endif
  noc_async_read_barrier();if(PROFILE){++io_barriers;}
  auto s=source+source_offset;
  limit=tile_begin+degree-1;vpos=0;stage_count=stage_index=0;target_lo=target_hi=0;
#if !AUX_ROWPTR && (TAIL_MERGE || PIPE_META)
  if(tile_begin!=0 || degree!=ud){error=22;return false;}
#endif
  begin_stage();
  for(uint32_t j=0;j<usedcount[bank];j++)hash[used[j]]=0;
  usedcount[bank]=0;
  bool probe_pressure=false;
  for(uint32_t j=0;j<degree;j++){
   uint32_t y=s[j],key=y+1,slot=hash_slot(y,tile_hash_mask);
   uint32_t probes=0;while(hash[slot]&&hash[slot]!=key){slot=(slot+1)&tile_hash_mask;HASH_COUNT(hash_insert_collisions);if(++probes>=PROBE_LIMIT)probe_pressure=true;}
   if(!hash[slot]){hash[slot]=key;used[usedcount[bank]++]=slot;}
  }
  // Existing row fits the small bank; observed insertion pressure can still
  // justify spending the other bank on a larger hash rather than preparation.
  if(POOL_BANKS && (epoch&(1u<<30)) && (epoch&(1u<<28)) && !pooled && probe_pressure){
   if(!wait(step)){error=17;return false;}
   auto enlarged_source=(uint32_t*)(base+SOURCE_OFFSET);
   for(uint32_t j=0;j<degree;j++)enlarged_source[source_offset+j]=s[j];
   for(uint32_t b=0;b<CONTEXTS;b++){
    auto oldhash=(uint32_t*)(base+HASH_OFFSET)+b*HASH_SIZE;
    auto oldused=(uint32_t*)(base+USED_OFFSET)+b*SOURCE_CAP;
    for(uint32_t k=0;k<usedcount[b];k++)oldhash[oldused[k]]=0;
    usedcount[b]=0;
   }
   ++promoted;bank=ctx=0;pooled=true;tile_hash_mask=2*HASH_SIZE-1;
   s=enlarged_source+source_offset;
   hash=(uint32_t*)(base+HASH_OFFSET);used=(uint32_t*)(base+USED_OFFSET);
   for(uint32_t j=0;j<degree;j++){
    uint32_t key=s[j]+1,slot=hash_slot(s[j],tile_hash_mask);
    while(hash[slot]&&hash[slot]!=key){slot=(slot+1)&tile_hash_mask;HASH_COUNT(hash_insert_collisions);}
    if(!hash[slot]){hash[slot]=key;used[usedcount[0]++]=slot;}
   }
  }
  // Only middle vertices preceding the largest owned closing vertex can contribute.
  finish_stage();return true;
 };
 while(!error){
  if(!tile_ready){
   ctx=active%CONTEXTS;
   if((epoch>>31) && !wait(step)){error=15;break;}
   if(!wait(laststep[ctx])){error=10;break;}
   if(!prepare_tile(ctx))break;
   tile_ready=true;++active;if(PROFILE)++tiles;
  }
  if(step>=0xfffffffeu){error=21;break;}
  uint32_t next=step+1,arena=(DUPLICATE_ARENAS?ctx*2:0)+(next-1)%2,off=16+((next-1)%RING_SLOTS)*16;
  if(next>RING_SLOTS && !wait(next-RING_SLOTS)){error=11;break;}
  if(DUPLICATE_ARENAS && !wait(arena_last[arena])){error=16;break;}
  auto desc=(uint32_t*)(base+JOBS_OFFSET)+arena*BATCH*8;
  uint32_t batch=0,words=0;
  while(batch<BATCH){
   if(target_lo==target_hi){
    if(vpos==limit)break;
    if(stage_index==stage_count){
     begin_stage();finish_stage();
    }
    target_v=staging[stage_index*32+2];target_lo=staging[stage_index*32];target_hi=staging[stage_index*32+1];
    if(target_hi<target_lo){error=2;break;}
    target_from=vpos+1>tile_begin?vpos+1-tile_begin:0;
    ++vpos;++stage_index;if(target_lo==target_hi)continue;
   }
   // Split a long row so every request fits the current arena, including alignment.
   uint32_t capacity=ARENA_WORDS-words;
   if(capacity<=target_lo%16)break;
   uint32_t amount=target_hi-target_lo;
   if(amount>capacity-target_lo%16)amount=capacity-target_lo%16;
   uint32_t hi=target_lo+amount,needed=((hi+15)&~15u)-(target_lo&~15u);
   if(!amount || needed>capacity){error=20;break;}
   read_col_range(target_lo,hi,(uint32_t)(targets+arena*ARENA_WORDS+words));
   auto d=desc+batch*8;d[0]=ctx;d[1]=target_from;d[2]=amount;
   d[3]=words+target_lo%16;d[4]=degree;d[5]=source_offset;d[6]=tile_hash_mask;
#if HIST_BINS
   d[7]=((label_of(source_u))*LABELS+label_of(target_v))*LABELS;
#endif
   if(PROFILE){candidates+=amount;target_bytes+=uint64_t(needed)*4;}
   words+=needed;++batch;target_lo=hi;
   if(words==ARENA_WORDS)break;
  }
  if(error)break;
  bool tile_done=vpos==limit && target_lo==target_hi;
  if(!batch){if(tile_done){tile_begin+=degree;tile_ready=false;continue;}error=20;break;}
  noc_async_read_barrier();if(PROFILE){++io_barriers;}sync[off+2]=batch;sync[off+11]=arena;
  asm volatile("fence" ::: "memory");sync[off]=next;step=next;
  const bool sharing=(epoch&(1u<<26)) && batch<GROUP;
  for(uint32_t group=0;group<batch;group+=(sharing?1:GROUP)){
   for(uint32_t lane=(NO_TRISC?0:3*CONSUMER_SLOTS);lane<GROUP;lane++){uint32_t k=sharing?group:group+lane;if(k>=batch)break;
    auto d=desc+k*8;uint32_t bank=d[0],cap=d[2],degree=d[4],mask=d[6];
    auto s=(uint32_t*)(base+SOURCE_OFFSET)+bank*SOURCE_CAP+d[5];
    auto hash=(uint32_t*)(base+HASH_OFFSET)+bank*HASH_SIZE;
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
    const uint32_t rank=3;
    if(use_binary){uint32_t first=from,nkeys=degree-from;from=first+nkeys*rank/GROUP;degree=first+nkeys*(rank+1)/GROUP;}
    else{uint32_t first=cap*rank/GROUP,last=cap*(rank+1)/GROUP;t+=first;cap=last-first;}
   }
#if PROFILE
   effective_probe_candidates+=cap;
#endif
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
   owncount+=c;
   }
  }
  laststep[ctx]=step;if(pooled)laststep[1]=step;arena_last[arena]=step;
  if(tile_done){tile_begin+=degree;tile_ready=false;}
 }
 if(!wait(step))error=13;
 sync[160]=tiles;sync[161]=tiles>>32;sync[162]=target_bytes;sync[163]=target_bytes>>32;sync[164]=meta_requests;sync[165]=meta_requests>>32;sync[166]=step;sync[167]=promoted;
 #if PROFILE
 sync[186]=effective_probe_candidates;sync[187]=effective_probe_candidates>>32;
 sync[178]=lookup_collision_steps;sync[179]=lookup_collision_steps>>32;sync[180]=hash_insert_collisions;sync[181]=hash_insert_collisions>>32;
 sync[182]=io_requests[2];sync[183]=io_requests[2]>>32;sync[184]=io_bytes[2];sync[185]=io_bytes[2]>>32;
 uint64_t io_values[]={io_requests[0],io_requests[1],io_bytes[0],io_bytes[1],io_barriers};
 for(uint32_t j=0;j<5;j++){sync[168+j*2]=io_values[j];sync[169+j*2]=io_values[j]>>32;}
 #endif
 sync[2]=error;sync[4]=sources;sync[5]=sources>>32;sync[6]=maxdegree;sync[7]=owncount;sync[8]=owncount>>32;sync[9]=candidates;sync[10]=candidates>>32;asm volatile("fence" ::: "memory");sync[1]=1;
 if(CHANNEL==1)return;
 uint32_t spins=0;while(true){invalidate_l1_cache();bool done=true;for(uint32_t w=0;w<3;w++)done &= sync[128+w*8+3]==epoch;if(done)break;if(++spins==SPIN_CAP){error=14;break;}}
 auto other=(volatile uint32_t*)get_common_arg_val<uint32_t>(1);invalidate_l1_cache();sources+=uint64_t(other[4])+(uint64_t(other[5])<<32);if(other[6]>maxdegree)maxdegree=other[6];error|=other[2];
 uint64_t count=owncount+uint64_t(other[7])+(uint64_t(other[8])<<32);for(uint32_t w=0;w<3;w++){count+=uint64_t(sync[128+w*8])+(uint64_t(sync[129+w*8])<<32);error|=sync[130+w*8];}
 for(uint32_t i=0;i<25;i++)result[i]=0;result[0]=count;result[1]=count>>32;result[2]=sources;result[3]=sources>>32;result[22]=error;result[23]=maxdegree;result[24]=cid;candidates+=uint64_t(other[9])+(uint64_t(other[10])<<32);result[26]=candidates;result[27]=candidates>>32;
 for(uint32_t k=0;k<3;k++){uint64_t v=uint64_t(sync[160+k*2])+(uint64_t(sync[161+k*2])<<32)+uint64_t(other[160+k*2])+(uint64_t(other[161+k*2])<<32);result[28+k*2]=v;result[29+k*2]=v>>32;}result[34]=sync[166]+other[166];result[35]=sync[167]+other[167];
 #if PROFILE
 uint64_t ep=uint64_t(sync[186])+(uint64_t(sync[187])<<32)+uint64_t(other[186])+(uint64_t(other[187])<<32);
 for(uint32_t w=0;w<3;w++){ep+=uint64_t(sync[134+w*8])+(uint64_t(sync[135+w*8])<<32);}
 result[60]=ep;result[61]=ep>>32;
 uint64_t hp=uint64_t(sync[178])+(uint64_t(sync[179])<<32)+uint64_t(other[178])+(uint64_t(other[179])<<32);
 for(uint32_t w=0;w<3;w++){hp+=uint64_t(sync[132+w*8])+(uint64_t(sync[133+w*8])<<32);}
 uint64_t hc=uint64_t(sync[180])+(uint64_t(sync[181])<<32)+uint64_t(other[180])+(uint64_t(other[181])<<32);
 result[50]=hp;result[51]=hp>>32;result[52]=hc;result[53]=hc>>32;
 // Publish aux IO for both DMs, including zero when AUX_ROWPTR=0.
 for(uint32_t j=0;j<2;j++){
  uint64_t v=uint64_t(sync[182+j*2])+(uint64_t(sync[183+j*2])<<32)
             +uint64_t(other[182+j*2])+(uint64_t(other[183+j*2])<<32);
  result[54+j*2]=uint32_t(v);
  result[55+j*2]=uint32_t(v>>32);
 }

 for(uint32_t j=0;j<5;j++){uint64_t v=uint64_t(sync[168+j*2])+(uint64_t(sync[169+j*2])<<32)+uint64_t(other[168+j*2])+(uint64_t(other[169+j*2])<<32);result[40+j*2]=v;result[41+j*2]=v>>32;}
 #endif
#if HIST_BINS
 auto allhist=(uint64_t*)get_common_arg_val<uint32_t>(HIST_BASE_ARG);
 for(uint32_t b=0;b<HIST_BINS;b++){
  uint64_t sum=allhist[b];for(uint32_t w=1;w<5;w++)sum+=allhist[w*HIST_BINS+b];allhist[b]=sum;
 }
 for(uint32_t pg=0;pg<HIST_PAGES;pg++)noc_async_write_tile(cid*HIST_PAGES+pg,histogram,(uint32_t)allhist+pg*PAGE_BYTES);
 noc_async_write_barrier();
#endif
 noc_async_write_tile(cid,output,(uint32_t)result);noc_async_write_barrier();
}
