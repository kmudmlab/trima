#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include "step_shared.hpp"
#include "../suite-v1/code/direct/algorithms.hpp"
#include "../suite-v1/code/direct/optimized.hpp"
#include "../suite-v1/code/direct/direct.hpp"
#undef HASH_SIZE
#undef ARENA_WORDS
struct HostIO {
    const std::vector<uint32_t>& row;
    const std::vector<uint32_t>& col;
    const std::vector<uint32_t>& aux;
    uint32_t r(uint32_t p) { return row.at(p); }
    uint32_t c(uint32_t p) { return col.at(p); }
    uint32_t a(uint32_t p) { return aux.at(p); }
    uint32_t get(uint32_t w,uint32_t p) { return w==0?r(p):w==1?c(p):a(p); }
    const uint32_t* span(uint32_t w,uint32_t p,uint32_t& length) {
        length=256-p%256; return (w==0?row:w==1?col:aux).data()+p;
    }
    uint32_t* fetch(uint32_t w,uint64_t lo,uint64_t hi,uint32_t* dst) {
        const auto& v=w==0?row:w==1?col:aux;
        for(uint64_t p=lo&~uint64_t(15);p<((hi+15)&~uint64_t(15));p++) { *dst++=p<v.size()?v[p]:0; }
        return dst-(((hi+15)&~uint64_t(15))-lo);
    }
    void wait() {} void target_batch() {} void metadata_batch() {}
};
std::vector<uint32_t> read(const char* path) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f) { throw std::runtime_error("read"); }
    auto bytes=f.tellg(); std::vector<uint32_t> v(size_t(bytes)/4);
    f.seekg(0); f.read(reinterpret_cast<char*>(v.data()),bytes); return v;
}
int main(int argc,char** argv) {
    try {
        if(argc!=5) { throw std::runtime_error("csr aux engines"); }
        auto raw=read(argv[1]),aux=read(argv[2]),mp=read(argv[4]); uint32_t n=raw[0],engines=std::stoul(argv[3]);
        std::vector<uint32_t> row(raw.begin()+2,raw.begin()+3+n),col(raw.begin()+3+n,raw.end());
        HostIO io{row,col,aux}; uint64_t total=0;
        std::cout<<"{\"engines\":[";
        for(uint32_t id=0;id<engines;id++) {
            std::vector<uint32_t> scratch(200000),hash(step_ring::HASH_SIZE),used(step_ring::SOURCE_CAP);
            auto base=steptc(io,n,id,engines,scratch.data(),step_ring::SOURCE_CAP);
            auto direct=steptc_direct(io,n,id,engines,scratch.data(),step_ring::SOURCE_CAP);
            if(base.error || direct.error || base.count!=direct.count || base.candidates!=direct.candidates) { throw std::runtime_error("baseline mismatch"); }
            for(uint32_t supply=0;supply<2;supply++) {
                for(uint32_t on=0;on<2;on++) {
                    uint64_t count[4]={},candidates[4]={},identity1=0,identity2=0,want1=0,want2=0; uint32_t nused=0;
                    std::fill(hash.begin(),hash.end(),0);
                    for(uint32_t u=id;u<n;u+=engines) {
                        uint32_t first=aux[u],last=aux[u+1],degree=row[u+1]-row[u];
                        if(first==last) { continue; }
                        const uint32_t* source=col.data()+row[u];
                        if(degree>step_ring::SOURCE_CAP) { throw std::runtime_error("source capacity"); }
                        if(degree>128) { step_ring::build_hash(source,degree,hash.data(),used.data(),nused); }
                        for(uint32_t t=first;t<last;t+=64) {
                            uint32_t end=std::min(64u,last-t); step_ring::Ref refs[64]; step_ring::Job jobs[64];
                            for(uint32_t k=0;k<end;k++) { auto v=aux[n+1+t+k]; if(mp[2*(t+k)]!=row[v] || mp[2*(t+k)+1]!=row[v+1]) { throw std::runtime_error("aux pointer mismatch"); } refs[k]={mp[2*(t+k)],mp[2*(t+k)+1],0,0}; }
                            for(uint32_t k=0;k<end;) {
                                uint32_t next=step_ring::plan(refs,k,end,jobs,u,degree,0,t);
                                if(next==k) { throw std::runtime_error("arena capacity"); }
                                std::vector<uint32_t> arena(step_ring::ARENA_WORDS,0xdeadbeef);
                                for(uint32_t j=k;j<next;j++) {
                                    auto& job=jobs[j-k];
                                    if(job.ordinal!=t+j || job.length!=refs[j].hi-refs[j].lo) { throw std::runtime_error("identity"); }
                                    if(supply) {
                                        io.fetch(1,refs[j].lo,refs[j].hi,arena.data()+job.target_offset-refs[j].lo%16);
                                    } else {
                                        for(uint32_t x=0;x<job.length;x++) { arena[job.target_offset+x]=io.get(1,refs[j].lo+x); }
                                    }
                                    step_ring::ProbeStats s; uint32_t owner=on?(j-k)%4:3;
                                    count[owner]+=step_ring::probe(job,source,hash.data(),arena.data()+job.target_offset,s);
                                    candidates[owner]+=s.candidates; identity1+=s.identity1; identity2+=s.identity2;
                                    for(uint64_t pos=0;pos<job.length;pos++) {
                                        want1+=(uint64_t(t+j)+1)*0x9e3779b1ull+pos;
                                        want2+=(uint64_t(u)+1)*(uint64_t(t+j)+1)+pos*pos;
                                    }
                                }
                                k=next;
                            }
                        }
                    }
                    uint64_t c=0,q=0;
                    for(uint32_t w=0;w<4;w++) { c+=count[w]; q+=candidates[w]; }
                    if(identity1!=want1 || identity2!=want2 || c!=base.count || q!=base.candidates) { throw std::runtime_error("ring count/candidates mismatch"); }
                }
            }
            if(id) { std::cout<<","; }
            std::cout<<"["<<base.count<<","<<base.candidates<<"]"; total+=base.count;
        }
        std::cout<<"],\"count\":"<<total<<"}\n";
    } catch(const std::exception& e) { std::cerr<<e.what()<<"\n"; return 1; }
    return 0;
}
