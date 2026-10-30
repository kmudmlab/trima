#pragma once
// Replay the device IO contract, including cache-backed span pointer lifetime.
struct HostIO {
    uint32_t* arrays[3];std::array<uint64_t,3> lens;
    uint32_t pw,slots[3];std::vector<uint32_t> tags[3],cache[3];
    uint64_t pages[3]={},requests[3]={},bytes[3]={},waits=0,batches=0,metadata=0;
    HostIO(uint32_t* r,uint32_t* c,uint32_t* a,std::array<uint64_t,3> lengths,uint32_t page_bytes):
        arrays{r,c,a},lens(lengths),pw(page_bytes/4),slots{16384/page_bytes,65536/page_bytes,16384/page_bytes}{
        for(uint32_t k=0;k<3;k++){tags[k].resize(slots[k]);cache[k].resize(slots[k]*pw);}
        reset();
    }
    void reset(){
        for(uint32_t k=0;k<3;k++){
            std::fill(tags[k].begin(),tags[k].end(),0xffffffffu);
            pages[k]=requests[k]=bytes[k]=0;
        }
        waits=batches=metadata=0;
    }
    uint32_t* fetch(uint32_t which,uint64_t lo,uint64_t hi,uint32_t* dst){
        if(hi<lo||hi>lens[which]){throw std::runtime_error("range out of input");}
        uint64_t begin=lo&~uint64_t(15),end=(hi+15)&~uint64_t(15);
        bytes[which]+=(end-begin)*4;
        if(end>begin){requests[which]+=(end-1)/pw-begin/pw+1;}
        for(uint64_t p=begin;p<end;p++){dst[p-begin]=p<lens[which]?arrays[which][p]:0;}
        return dst+lo%16;
    }
    void wait(){++waits;}
    void target_batch(){++batches;}
    void metadata_batch(){++metadata;}
    uint32_t get(uint32_t which,uint32_t i){
        if(i>=lens[which]){throw std::runtime_error("get out of input");}
        uint32_t page=i/pw,slot=page%slots[which];
        if(tags[which][slot]!=page){
            uint64_t first=uint64_t(page)*pw;
            for(uint32_t j=0;j<pw;j++){cache[which][slot*pw+j]=first+j<lens[which]?arrays[which][first+j]:0;}
            tags[which][slot]=page;++pages[which];++waits;
        }
        return cache[which][slot*pw+i%pw];
    }
    const uint32_t* span(uint32_t which,uint32_t i,uint32_t& size){
        get(which,i);size=pw-i%pw;
        return cache[which].data()+((i/pw)%slots[which])*pw+i%pw;
    }
    uint32_t r(uint32_t i){return get(0,i);}
    uint32_t c(uint32_t i){return get(1,i);}
    uint32_t a(uint32_t i){return get(2,i);}
    std::array<uint64_t,12> counters()const{
        return {pages[0],pages[1],pages[2],requests[0],requests[1],requests[2],bytes[0],bytes[1],bytes[2],waits,batches,metadata};
    }
};
