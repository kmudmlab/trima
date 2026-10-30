// Step B: frozen TRUST 2DM (frozen-tt/trust/trust_p150_kernel.cpp) with TriMA features
// added one switch at a time. Source ownership and the per-source hash reuse are unchanged.
//   PRUNE        skip the largest source neighbor; ignore target keys above it (TriMA R:93, R:185)
//   HASH_OA      TriMA open addressing, x^(x>>16), cleared by used list (TriMA R:95-102)
//   DIRECT       batched row-pointer reads + exact target ranges into an arena, one barrier per batch
//   LOOKUP_WIDTH grouped probes as TriMA R:221-233 (DIRECT + HASH_OA only)
#include <stdint.h>
#include "api/dataflow/dataflow_api.h"
#if PROFILE
#define ADD(x,v) x += (v)
#else
#define ADD(x,v)
#endif
void kernel_main(){
    const uint32_t gx=get_common_arg_val<uint32_t>(3),nc=get_common_arg_val<uint32_t>(4);
    const uint32_t n=get_common_arg_val<uint32_t>(5),begin=get_common_arg_val<uint32_t>(6),end=get_common_arg_val<uint32_t>(7);
    const uint32_t mod=get_common_arg_val<uint32_t>(8),rem=get_common_arg_val<uint32_t>(9);
    const uint32_t cid=get_absolute_logical_y()*gx+get_absolute_logical_x();
    const uint32_t id=cid*ENGINES+ENGINE,workers=nc*ENGINES;
    // GENERATED_ACCESSORS
    const uint32_t base=get_write_ptr(ENGINE);
    auto bins=(uint32_t*)(base+BINS_OFF);auto table=(uint32_t*)(base+TABLE_OFF);
    auto hash=(uint32_t*)(base+HASH_OFF);auto used=(uint32_t*)(base+USED_OFF);
    auto srcbuf=(uint32_t*)(base+SOURCE_OFF);
    auto rt=(uint32_t*)(base+TAGS_OFF);auto ct=rt+ROW_SLOTS;
    const uint32_t row_base=base+ROWC_OFF,col_base=row_base+ROW_SLOTS*PAGE_BYTES;
    auto stage=(uint32_t*)(base+STAGE_OFF);auto arena=(uint32_t*)(base+ARENA_OFF);
    auto result=(uint32_t*)(base+RESULT_OFF);
    for(uint32_t i=0;i<ROW_SLOTS;i++)rt[i]=0xffffffff;
    for(uint32_t i=0;i<COL_SLOTS;i++)ct[i]=0xffffffff;
#if HASH_OA
    for(uint32_t i=0;i<HASH_SIZE;i++)hash[i]=0;
    uint32_t nused=0;
#endif
    uint64_t count=0,source_count=0,candidates=0,row_pages=0,col_pages=0,batches=0;
    uint32_t error=0,max_bin=0;
    auto row=[&](uint32_t i)->uint32_t{
        uint32_t pg=i/PAGE_WORDS,slot=pg%ROW_SLOTS;
        if(rt[slot]!=pg){read_row_page(pg,row_base+slot*PAGE_BYTES);noc_async_read_barrier();rt[slot]=pg;ADD(row_pages,1);}
        return ((uint32_t*)(row_base+slot*PAGE_BYTES))[i%PAGE_WORDS];
    };
    auto col_page=[&](uint32_t i)->uint32_t*{
        uint32_t pg=i/PAGE_WORDS,slot=pg%COL_SLOTS;
        if(ct[slot]!=pg){read_col_page(pg,col_base+slot*PAGE_BYTES);noc_async_read_barrier();ct[slot]=pg;ADD(col_pages,1);}
        return (uint32_t*)(col_base+slot*PAGE_BYTES);
    };
    uint32_t mask=0;
    auto probe=[&](uint32_t w)->uint32_t{
#if HASH_OA
        uint32_t key=w+1,slot=(w^(w>>16))&(HASH_SIZE-1),x;
        while((x=hash[slot])&&x!=key)slot=(slot+1)&(HASH_SIZE-1);
        return x==key;
#else
        uint32_t b=w&mask,sz=bins[b];
        for(uint32_t z=0;z<sz;z++)if(table[b*BUCKET_CAP+z]==w)return 1;
        return 0;
#endif
    };
    for(uint64_t seq=id;;seq+=workers){
        uint64_t u64=uint64_t(begin)+rem+seq*mod;if(u64>=end)break;
        uint32_t u=u64,first,last;
#if DIRECT
        read_row_range(u,u+2,(uint32_t)stage);noc_async_read_barrier();first=stage[u%16];last=stage[u%16+1];
#else
        first=row(u);last=row(u+1);
#endif
        uint32_t degree=last-first;
        if(degree<2)continue;
        if(degree>SOURCE_CAP){error=1;break;}
        ++source_count;
        const uint32_t* source;
#if DIRECT
        read_col_range(first,last,(uint32_t)srcbuf);noc_async_read_barrier();source=srcbuf+first%16;
#else
        for(uint32_t j=0;j<degree;){
            auto page=col_page(first+j);uint32_t stop=((first+j)/PAGE_WORDS+1)*PAGE_WORDS-first;if(stop>degree)stop=degree;
            for(;j<stop;j++)srcbuf[j]=page[(first+j)%PAGE_WORDS];
        }
        source=srcbuf;
#endif
#if HASH_OA
        for(uint32_t k=0;k<nused;k++)hash[used[k]]=0;
        nused=0;
        for(uint32_t j=0;j<degree;j++){
            uint32_t y=source[j],key=y+1,slot=(y^(y>>16))&(HASH_SIZE-1);
            while(hash[slot]&&hash[slot]!=key)slot=(slot+1)&(HASH_SIZE-1);
            if(!hash[slot]){hash[slot]=key;used[nused++]=slot;}
        }
#else
        uint32_t nb=degree>100?1024:32;mask=nb-1;
        for(uint32_t b=0;b<nb;b++)bins[b]=0;
        for(uint32_t j=0;j<degree;j++){
            uint32_t v=source[j],b=v&mask,at=bins[b]++;
            if(at>=BUCKET_CAP){error=2;break;}
            table[b*BUCKET_CAP+at]=v;if(at+1>max_bin)max_bin=at+1;
        }
        if(error)break;
#endif
        const uint32_t jend=PRUNE?degree-1:degree,maxkey=source[degree-1];
#if DIRECT
        for(uint32_t j0=0;j0<jend&&!error;j0+=META_STAGE){
            uint32_t cnt=jend-j0;if(cnt>META_STAGE)cnt=META_STAGE;
            for(uint32_t k=0;k<cnt;k++){uint32_t v=source[j0+k];if(v>=n){error=3;break;}read_row_range(v,v+2,(uint32_t)(stage+k*32));}
            noc_async_read_barrier();if(error)break;
            for(uint32_t k=0;k<cnt;k++){uint32_t v=source[j0+k],a=stage[k*32+v%16],b=stage[k*32+v%16+1];stage[k*32]=a;stage[k*32+1]=b;}
            for(uint32_t k=0;k<cnt&&!error;){
                uint32_t words=0,k1=k;
                while(k1<cnt){
                    uint32_t lo=stage[k1*32],hi=stage[k1*32+1];
                    if(hi<lo){error=4;break;}
                    if(hi==lo){stage[k1*32+2]=0;++k1;continue;}
                    uint32_t need=((hi+15)&~15u)-(lo&~15u);
                    if(need>ARENA_WORDS){error=20;break;}
                    if(words+need>ARENA_WORDS)break;
                    read_col_range(lo,hi,(uint32_t)(arena+words));stage[k1*32+2]=words+lo%16;words+=need;++k1;
                }
                if(error)break;
                noc_async_read_barrier();ADD(batches,1);
                for(uint32_t q=k;q<k1;q++){
                    uint32_t cap=stage[q*32+1]-stage[q*32];if(!cap)continue;
                    const uint32_t* t=arena+stage[q*32+2];
#if PRUNE
                    if(t[cap-1]>maxkey){uint32_t l=0,h=cap;while(l<h){uint32_t mid=l+(h-l)/2;if(t[mid]<=maxkey)l=mid+1;else h=mid;}cap=l;}
#endif
                    ADD(candidates,cap);uint32_t a=0;
#if LOOKUP_WIDTH > 1
                    for(;a+LOOKUP_WIDTH<=cap;a+=LOOKUP_WIDTH){
                        uint32_t keys[LOOKUP_WIDTH],slots[LOOKUP_WIDTH],values[LOOKUP_WIDTH];
#pragma GCC unroll 8
                        for(uint32_t z=0;z<LOOKUP_WIDTH;z++){uint32_t y=t[a+z];keys[z]=y+1;slots[z]=(y^(y>>16))&(HASH_SIZE-1);values[z]=hash[slots[z]];}
#pragma GCC unroll 8
                        for(uint32_t z=0;z<LOOKUP_WIDTH;z++){uint32_t x=values[z],slot=slots[z];while(x&&x!=keys[z]){slot=(slot+1)&(HASH_SIZE-1);x=hash[slot];}if(x==keys[z])++count;}
                    }
#endif
                    for(;a<cap;a++)count+=probe(t[a]);
                }
                k=k1;
            }
        }
#else
        for(uint32_t j=0;j<jend;j++){
            uint32_t v=source[j];if(v>=n){error=3;break;}
            uint32_t lo=row(v),hi=row(v+1);
            for(uint32_t k=lo;k<hi;){
                auto page=col_page(k);
                uint32_t stop=(k/PAGE_WORDS+1)*PAGE_WORDS;if(stop>hi)stop=hi;
                for(;k<stop;k++){
                    uint32_t w=page[k%PAGE_WORDS];
#if PRUNE
                    if(w>maxkey){k=hi;break;}
#endif
                    ADD(candidates,1);count+=probe(w);
                }
            }
        }
#endif
        if(error)break;
    }
    uint64_t values[]={count,source_count,candidates,row_pages,col_pages,batches};
    for(uint32_t j=0;j<6;j++){result[2*j]=uint32_t(values[j]);result[2*j+1]=uint32_t(values[j]>>32);}
    result[22]=error;result[23]=max_bin;result[24]=id;
    noc_async_write_tile(id,output,(uint32_t)result);noc_async_write_barrier();
}
