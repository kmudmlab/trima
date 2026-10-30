#include <stdint.h>
#include "api/dataflow/dataflow_api.h"
constexpr uint32_t POOL_BYTES=64u*1024u*1024u,PAGE_BYTES=16384u;
constexpr uint32_t ADDR_OFFSET=512u*1024u,SYNC_OFFSET=544u*1024u,OUT_OFFSET=560u*1024u;
inline uint32_t mix32(uint32_t x) {
    x^=x>>16; x*=0x7feb352du; x^=x>>15; x*=0x846ca68bu; return x^(x>>16);
}
inline uint32_t location(uint32_t k,uint32_t id,uint32_t size,uint32_t random,uint32_t seed) {
    if(!random) { return (id*65536u+k*size)&(POOL_BYTES-1); }
    uint32_t h=mix32(k^mix32(id+seed));
    uint32_t page=h%(POOL_BYTES/PAGE_BYTES);
    uint32_t offset=(mix32(h^0x9e3779b9u)%((PAGE_BYTES-size)/64u+1u))*64u;
    return page*PAGE_BYTES+offset;
}
inline void put64(uint32_t* p,uint32_t at,uint64_t x) { p[at]=uint32_t(x); p[at+1]=uint32_t(x>>32); }
void kernel_main() {
    // ACCESSORS
    const uint32_t gx=get_common_arg_val<uint32_t>(3),engines=get_common_arg_val<uint32_t>(4);
    const uint32_t total=get_common_arg_val<uint32_t>(5),n=get_common_arg_val<uint32_t>(6);
    const uint32_t size=get_common_arg_val<uint32_t>(7),batch=get_common_arg_val<uint32_t>(8);
    const uint32_t random=get_common_arg_val<uint32_t>(9),seed=get_common_arg_val<uint32_t>(10);
    const uint32_t epoch=get_common_arg_val<uint32_t>(11),verify_all=get_common_arg_val<uint32_t>(12);
    const uint32_t spin_ticks=get_common_arg_val<uint32_t>(13);
    const uint32_t id=(get_absolute_logical_y()*gx+get_absolute_logical_x())*engines+ENGINE;
    uintptr_t base=get_write_ptr(ENGINE);
    auto addr=(uint64_t*)(base+ADDR_OFFSET);
    auto sync=(uint32_t*)(base+SYNC_OFFSET);
    auto out=(uint32_t*)(base+OUT_OFFSET);
    uint32_t error=0;
    for(uint32_t k=0;k<1024;k++) { out[k]=0; }
    for(uint32_t k=0;k<n;k++) {
        uint32_t offset=location(k,id,size,random,seed);
        addr[k]=get_noc_addr(offset/PAGE_BYTES,input)+(offset%PAGE_BYTES);
    }
    if(total>1) {
        for(uint32_t k=0;k<16;k++) { sync[k]=0; }
        sync[0]=epoch;
        noc_async_write_tile(id,control,(uintptr_t)sync); noc_async_write_barrier();
        uint64_t gate_start=get_timestamp();
        if(id==0) {
            bool ready=false;
            while(!ready) {
                for(uint32_t k=0;k<total;k++) {
                    noc_async_read_tile(k,control,(uintptr_t)(sync+16*k));
                    if((k+1)%32==0) { noc_async_read_barrier(); }
                }
                noc_async_read_barrier(); ready=true;
                for(uint32_t k=0;k<total;k++) { if(sync[16*k]!=epoch) { ready=false; } }
                if(get_timestamp()-gate_start>5000000000ull) { error=1; break; }
            }
            sync[0]=epoch; sync[1]=error;
            noc_async_write_tile(220,control,(uintptr_t)sync); noc_async_write_barrier();
        } else {
            do {
                noc_async_read_tile(220,control,(uintptr_t)sync); noc_async_read_barrier();
                if(get_timestamp()-gate_start>5000000000ull) { error=2; break; }
            } while(sync[0]!=epoch);
            if(sync[0]==epoch && sync[1]) { error=3; }
        }
    }
    uint64_t start=get_timestamp();
    if(!error) {
        if(spin_ticks) {
            while(get_timestamp()-start<spin_ticks) { asm volatile("" ::: "memory"); }
        } else {
            for(uint32_t first=0;first<n;first+=batch) {
                uint32_t count=(n-first<batch)?n-first:batch;
                for(uint32_t j=0;j<count;j++) { noc_async_read(addr[first+j],base+j*size,size); }
                noc_async_read_barrier();
                if(verify_all) {
                    for(uint32_t j=0;j<count;j++) {
                        uint32_t word=location(first+j,id,size,random,seed)/4;
                        auto data=(volatile uint32_t*)(base+j*size);
                        for(uint32_t w=0;w<size/4;w++) { if(data[w]!=((word+w)^0xa5a55a5au)) { error=4; } }
                    }
                }
            }
        }
    }
    uint64_t stop=get_timestamp();
    if(n && !spin_ticks && !error) {
        uint32_t first=((n-1)/batch)*batch;
        for(uint32_t j=0;j<n-first;j++) {
            uint32_t word=location(first+j,id,size,random,seed)/4;
            auto data=(volatile uint32_t*)(base+j*size);
            for(uint32_t w=0;w<size/4;w++) { if(data[w]!=((word+w)^0xa5a55a5au)) { error=5; } }
        }
    }
    out[0]=0x4e4f4331u; out[1]=id; out[2]=error; out[3]=n; out[4]=size; out[5]=batch;
    out[6]=total; out[7]=random; put64(out,8,stop-start); out[10]=epoch;
    out[11]=n?(n+batch-1)/batch:0; out[12]=verify_all; out[13]=spin_ticks;
    put64(out,14,start); put64(out,16,stop);
    noc_async_write_tile(id,output,(uintptr_t)out); noc_async_write_barrier();
}
