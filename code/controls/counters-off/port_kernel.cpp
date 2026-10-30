#include <stdint.h>
#include "api/dataflow/dataflow_api.h"
// ALGORITHMS
template<class Reader> struct IO {
    uint32_t* cache;uint32_t* tags;uint64_t reads[3]={0,0,0};
    Reader& read;
    uint32_t get(uint32_t which,uint32_t index){
        uint32_t slots=which==1?COL_SLOTS:which==0?ROW_SLOTS:AUX_SLOTS;
        uint32_t tagbase=which==0?0:(which==1?ROW_SLOTS:ROW_SLOTS+COL_SLOTS);
        uint32_t pg=index/PAGE_WORDS,slot=pg%slots,at=tagbase+slot;
        if(tags[at]!=pg){
            read(which,pg,(uint32_t)(cache+at*PAGE_WORDS));
            noc_async_read_barrier();tags[at]=pg;
        }
        return cache[at*PAGE_WORDS+index%PAGE_WORDS];
    }
    const uint32_t* span(uint32_t which,uint32_t index,uint32_t& size){
        get(which,index);uint32_t slots=which==1?COL_SLOTS:which==0?ROW_SLOTS:AUX_SLOTS;
        uint32_t tagbase=which==0?0:(which==1?ROW_SLOTS:ROW_SLOTS+COL_SLOTS);
        size=PAGE_WORDS-index%PAGE_WORDS;
        return cache+(tagbase+(index/PAGE_WORDS)%slots)*PAGE_WORDS+index%PAGE_WORDS;
    }
    uint32_t r(uint32_t i){return get(0,i);}uint32_t c(uint32_t i){return get(1,i);}uint32_t a(uint32_t i){return get(2,i);}
};
void kernel_main(){
    // ACCESSOR_SETUP
    uint32_t gx=get_common_arg_val<uint32_t>(0),cores=get_common_arg_val<uint32_t>(1),n=get_common_arg_val<uint32_t>(2),m=get_common_arg_val<uint32_t>(3);
    uint32_t id=(get_absolute_logical_y()*gx+get_absolute_logical_x())*ENGINES+ENGINE;
    auto base=(uint32_t*)get_write_ptr(ENGINE);auto tags=base+(ROW_SLOTS+COL_SLOTS+AUX_SLOTS)*PAGE_WORDS;
    for(uint32_t i=0;i<ROW_SLOTS+COL_SLOTS+AUX_SLOTS;i++)tags[i]=0xffffffffu;
    // IO_INIT
    auto scratch=tags+((ROW_SLOTS+COL_SLOTS+AUX_SLOTS+31)/32)*32;
    Counters s;
#if MODE==1
    s=OPT_LEVEL?tricore_staged(io,n,m,id,cores*ENGINES,scratch):tricore(io,n,m,id,cores*ENGINES,scratch);
#elif MODE==2
    s=OPT_LEVEL?wetric_staged(io,n,id,cores*ENGINES,SPREAD,TAIL,scratch):wetric(io,n,id,cores*ENGINES,SPREAD,TAIL);
#elif MODE==3
    s=steptc(io,n,id,cores*ENGINES,scratch,SOURCE_CAP);
#elif MODE==4
    s=OPT_LEVEL?btc_staged(io,id,cores*ENGINES,scratch):btc_scalar(io,id,cores*ENGINES);
#else
    s=trust_packed(io,n,id,cores*ENGINES,scratch,SOURCE_CAP);
#endif
    // Source algorithms have finished; reuse cache memory for the output page.
    for(uint32_t j=0;j<1024;j++)base[j]=0;
    uint64_t values[]={s.count,s.jobs,s.candidates,s.probes,io.reads[0],io.reads[1],io.reads[2]};
    for(uint32_t j=0;j<7;j++){base[2*j]=values[j];base[2*j+1]=values[j]>>32;}
    base[22]=s.error;base[24]=id;base[25]=0x504f5254;
    noc_async_write_tile(id,output,(uint32_t)base);noc_async_write_barrier();
}
