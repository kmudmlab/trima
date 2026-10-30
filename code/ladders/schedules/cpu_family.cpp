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
struct IO {
    const std::vector<uint32_t>& rp; const std::vector<uint32_t>& col; const std::vector<uint32_t>& aux;
    uint32_t r(uint32_t p){return rp.at(p);} uint32_t c(uint32_t p){return col.at(p);} uint32_t a(uint32_t p){return aux.at(p);}
    uint32_t get(uint32_t w,uint32_t p){return w==0?r(p):w==1?c(p):a(p);}
    const uint32_t* span(uint32_t w,uint32_t p,uint32_t& n){n=64-p%64;return (w==0?rp:w==1?col:aux).data()+p;}
    uint32_t* fetch(uint32_t w,uint64_t lo,uint64_t hi,uint32_t* dst){
        auto& arr=w==0?rp:w==1?col:aux;
        for(uint64_t p=lo&~uint64_t(15);p<((hi+15)&~uint64_t(15));p++){dst[p-(lo&~uint64_t(15))]=p<arr.size()?arr[p]:0;}
        return dst+lo%16;
    }
    void wait(){} void target_batch(){} void metadata_batch(){}
};
std::vector<uint32_t> load(const char* path){
    std::ifstream f(path,std::ios::binary|std::ios::ate);if(!f){throw std::runtime_error("read");}
    auto bytes=f.tellg();std::vector<uint32_t> a(size_t(bytes)/4);f.seekg(0);f.read(reinterpret_cast<char*>(a.data()),bytes);return a;
}
int main(int argc,char**argv){try{
    if(argc!=5){return 2;}
    auto raw=load(argv[1]),aux=load(argv[2]),mp=load(argv[4]);uint32_t n=raw[0],m=raw[1],engines=std::stoul(argv[3]);
    std::vector<uint32_t> rp(raw.begin()+2,raw.begin()+n+3),col(raw.begin()+n+3,raw.end());IO io{rp,col,aux};
    for(uint32_t e=0;e<m;e++){if(mp[2ull*e]!=rp[col[e]]||mp[2ull*e+1]!=rp[col[e]+1]){throw std::runtime_error("M identity");}}
    uint64_t total=0;std::cout<<"{\"engines\":[";
    for(uint32_t id=0;id<engines;id++){
        std::vector<uint32_t> scratch(200000),hash(16384);step_ring::ProbeStats stats;uint64_t count=0,want1=0,want2=0;
#if FAMILY == 2
        auto baseline=wetric_staged(io,n,id,engines,127,0,scratch.data());
        auto direct=wetric_direct(io,n,id,engines,127,scratch.data(),2240);
        auto pref=[&](uint32_t u){return uint64_t(aux[2ull*u])+(uint64_t(aux[2ull*u+1])<<32);};
        // Independent scalar wedge ordinal walk, retaining original chunk ownership.
        uint64_t ordinal=0;
        for(uint32_t u=0;u<n;u++){
            uint32_t degree=rp[u+1]-rp[u];
            for(uint32_t j=0;j+1<degree;j++){
                for(uint32_t k=j+1;k<degree;k++,ordinal++){
                    if((ordinal/127)%engines!=id){continue;}
                    uint32_t e=rp[u]+j,lo=mp[2ull*e],hi=mp[2ull*e+1];
                    step_ring::Job job{u,degree,0,0,hi-lo,k,k+1,j};
                    count+=step_ring::probe(job,col.data()+rp[u],hash.data(),col.data()+lo,stats);
                    want1+=(uint64_t(u)+1)*0x9e3779b1ull+(uint64_t(j)+1)*0x85ebca6bull+k;
                    want2+=(uint64_t(u)+1)*(uint64_t(j)+1)+uint64_t(k)*k;
                }
            }
            if(ordinal!=pref(u+1)){throw std::runtime_error("prefix identity");}
        }
#else
        auto baseline=tricore_coo_staged(io,n,m,id,engines,scratch.data());
        auto direct=tricore_coo_direct(io,n,m,id,engines,scratch.data(),2240);
        for(uint64_t first=uint64_t(id)*32;first<m;first+=uint64_t(engines)*32){
            for(uint32_t e=first;e<std::min(uint64_t(m),first+32);e++){
                uint32_t u=aux[e],lo=mp[2ull*e],hi=mp[2ull*e+1],degree=rp[u+1]-rp[u];
                auto src=col.data()+rp[u],target=col.data()+lo,lr=src,sr=target;uint32_t len=degree,slen=hi-lo;
                if(len<slen){std::swap(lr,sr);std::swap(len,slen);}
                for(uint32_t z=0;z<32;z++){hash[z]=len?lr[uint64_t(z)*len/32]:0;}
                step_ring::Job job{u,degree,0,0,hi-lo,0,e,0};count+=step_ring::probe(job,src,hash.data(),target,stats);
                for(uint32_t x=0;x<slen;x++){
                    if(!len||sr[x]<lr[0]||sr[x]>lr[len-1]){continue;}
                    want1+=(uint64_t(e)+1)*0x9e3779b1ull+x;
                    want2+=(uint64_t(u)+1)*(uint64_t(e)+1)+uint64_t(x)*x;
                }
            }
        }
#endif
        if(baseline.error||direct.error||count!=baseline.count||count!=direct.count||stats.candidates!=baseline.candidates||stats.candidates!=direct.candidates||stats.identity1!=want1||stats.identity2!=want2){throw std::runtime_error("count/candidate/identity mismatch");}
        if(id){std::cout<<",";}std::cout<<"["<<count<<","<<stats.candidates<<","<<want1<<","<<want2<<"]";total+=count;
    }
    std::cout<<"],\"count\":"<<total<<"}\n";
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
