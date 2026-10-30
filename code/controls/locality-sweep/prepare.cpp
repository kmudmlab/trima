#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <array>
#include <map>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include "algorithms.hpp"
#include "optimized.hpp"
#include "direct.hpp"
struct Map {
    int fd;size_t bytes;uint32_t* data;
    Map(const char* path,size_t length=0){
        fd=open(path,length?O_RDWR|O_CREAT|O_EXCL:O_RDONLY,0600);
        if(fd<0)throw std::runtime_error("cannot open (output must be new)");
        if(length&&ftruncate(fd,length))throw std::runtime_error("ftruncate");
        struct stat st;if(fstat(fd,&st))throw std::runtime_error("fstat");bytes=st.st_size;
        data=(uint32_t*)mmap(nullptr,bytes,length?PROT_READ|PROT_WRITE:PROT_READ,MAP_SHARED,fd,0);
        if(data==MAP_FAILED)throw std::runtime_error("mmap");
    }
    ~Map(){munmap(data,bytes);close(fd);}
};
#include "replay_io.hpp"

int main(int argc,char** argv){try{
    if(argc<5)throw std::runtime_error("prepare input.csr aux.bin mode tail [test-engines]");
    Map input(argv[1]);uint32_t n=input.data[0],m=input.data[1];
    if(!n||uint64_t(n)>=0x7fffffffu||uint64_t(m)>=0x7fffffffu||input.bytes!=4*(uint64_t(n)+m+3))throw std::runtime_error("CSR dimensions");
    uint32_t* rp=input.data+2;uint32_t* col=rp+n+1;uint32_t run_mode=std::stoul(argv[3]),mode=run_mode==7?3:run_mode==8?2:(run_mode==9||run_mode==10)?6:run_mode,tail=std::min(n,(uint32_t)std::stoul(argv[4])),cap=0;
    if(rp[0]||rp[n]!=m)throw std::runtime_error("CSR offsets");
    for(uint32_t u=0;u<n;u++){
        if(rp[u+1]<rp[u]||rp[u+1]>m)throw std::runtime_error("CSR offsets");
        cap=std::max(cap,rp[u+1]-rp[u]);
        for(uint32_t j=rp[u];j<rp[u+1];j++)if(col[j]<=u||col[j]>=n||(j>rp[u]&&col[j-1]>=col[j]))throw std::runtime_error("numeric-forward unique sorted CSR required");
    }
    uint64_t words=32,total=0,tasks=0;
    std::map<uint64_t,std::array<uint32_t,16>> blocks;
    uint32_t nr=(n+15)/16;
    if(mode==4){
        for(uint32_t u=0;u<n;u++)for(uint32_t e=rp[u];e<rp[u+1];e++){
            uint32_t v=col[e];blocks[(uint64_t(u/16)<<32)+(v/32)][u%16]|=1u<<(v%32);
        }
        words=2+uint64_t(nr)+1+17*uint64_t(blocks.size());tasks=blocks.size();
    }
    if(mode==2)words=2*(uint64_t(n)+1)+(uint64_t(tail)*(tail-1)/2+31)/32;
    if(mode==3)words=uint64_t(n)+1+m;
    if(mode==6)words=std::max(uint64_t(m),uint64_t(32));
    if(words>=0x100000000ull)throw std::runtime_error("aux uint32 index limit");
    Map aux(argv[2],words*4);
    if(mode==6){for(uint32_t u=0;u<n;u++)for(uint32_t e=rp[u];e<rp[u+1];e++)aux.data[e]=u;}
    if(mode==4){
        aux.data[0]=nr;aux.data[1]=blocks.size();auto p=aux.data+2;auto ix=p+nr+1;auto bits=ix+blocks.size();uint32_t j=0;
        for(const auto& kv:blocks){uint32_t i=kv.first>>32;++p[i+1];ix[j]=(uint32_t)kv.first;
            for(uint32_t r=0;r<16;r++)bits[j*16+r]=kv.second[r];++j;}
        for(uint32_t i=0;i<nr;i++)p[i+1]+=p[i];
    }else if(mode==2){
        auto p=(uint64_t*)aux.data;p[0]=0;
        for(uint32_t u=0;u<n;u++){uint64_t d=rp[u+1]-rp[u];p[u+1]=p[u]+d*(d-1)/2;}
        total=p[n];auto bitmap=aux.data+2*(n+1);
        for(uint32_t u=n-tail;u<n;u++)for(uint32_t j=rp[u];j<rp[u+1];j++){
            uint64_t bit=uint64_t(u-(n-tail))*(2*uint64_t(tail)-(u-(n-tail))-1)/2+(col[j]-u-1);
            bitmap[bit/32]|=1u<<(bit%32);
        }
    }else if(mode==3){
        auto owner=[&](uint32_t u,uint32_t v){uint32_t du=rp[u+1]-rp[u],dv=rp[v+1]-rp[v];
            if(!du||!dv)return n;if(std::max(du,dv)<=128)return u;
            return du>dv||(du==dv&&u>v)?u:v;};
        auto p=aux.data;auto targets=p+n+1;
        for(uint32_t u=0;u<n;u++)for(uint32_t j=rp[u];j<rp[u+1];j++){uint32_t o=owner(u,col[j]);if(o<n)++p[o+1];}
        for(uint32_t u=0;u<n;u++)p[u+1]+=p[u];tasks=p[n];
        std::vector<uint32_t> cursor(p,p+n);
        for(uint32_t u=0;u<n;u++)for(uint32_t j=rp[u];j<rp[u+1];j++){uint32_t v=col[j],o=owner(u,v);if(o<n)targets[cursor[o]++]=o==u?v:u;}
        for(uint32_t u=0;u<n;u++)std::sort(targets+p[u],targets+p[u+1]);
    }
    std::cout<<"{\"n\":"<<n<<",\"m\":"<<m<<",\"maxdegree\":"<<cap<<",\"aux_words\":"<<words<<",\"wedges\":"<<total<<",\"tasks\":"<<tasks;
    if(argc>5){
        uint32_t engines=std::stoul(argv[5]);HostIO io(rp,col,aux.data,{uint64_t(n)+1,uint64_t(m),words},mode==3?1024:256);std::vector<uint32_t> scratch(std::max(16384u,2*std::max(cap,32u)+2049)+ARENA_WORDS+META_STAGE*40+HASH_SIZE+4*cap+4096);uint64_t count=0,jobs=0;std::array<uint64_t,12> totals{};std::vector<uint64_t> cand;std::vector<std::array<uint64_t,12>> per_engine_io;
        std::cout<<",\"engine_counts\":[";
        for(uint32_t id=0;id<engines;id++){
            io.reset();Counters s;
            if(run_mode==7)s=steptc_direct(io,n,id,engines,scratch.data(),cap);
            else if(run_mode==8)s=wetric_direct(io,n,id,engines,127,scratch.data(),cap);
            else if(run_mode==9)s=tricore_coo_direct(io,n,m,id,engines,scratch.data(),cap);
            else if(run_mode==10)s=tricore_coo_grid(io,n,m,id,engines,scratch.data());
            else if(mode==1)s=OPT_LEVEL?tricore_staged(io,n,m,id,engines,scratch.data()):tricore(io,n,m,id,engines,scratch.data());
            else if(mode==6)s=OPT_LEVEL?tricore_coo_staged(io,n,m,id,engines,scratch.data()):tricore_coo_original(io,n,m,id,engines,scratch.data());
            else if(mode==2)s=OPT_LEVEL?wetric_staged(io,n,id,engines,127,tail,scratch.data()):wetric(io,n,id,engines,127,tail);
            else if(mode==3)s=steptc(io,n,id,engines,scratch.data(),cap);
            else if(mode==4)s=OPT_LEVEL?btc_staged(io,id,engines,scratch.data()):btc_scalar(io,id,engines);
            else s=trust_packed(io,n,id,engines,scratch.data(),cap);
            if(s.error)throw std::runtime_error("algorithm error");count+=s.count;jobs+=s.jobs;cand.push_back(s.candidates);auto counters=io.counters();per_engine_io.push_back(counters);for(size_t k=0;k<12;k++){totals[k]+=counters[k];}if(id)std::cout<<",";std::cout<<s.count;
        }
        std::cout<<"],\"engine_candidates\":[";for(size_t k=0;k<cand.size();k++){if(k){std::cout<<",";}std::cout<<cand[k];}
        std::cout<<"],\"io\":[";for(size_t k=0;k<12;k++){if(k){std::cout<<",";}std::cout<<totals[k];}
        std::cout<<"],\"engine_io\":[";for(size_t i=0;i<per_engine_io.size();i++){if(i){std::cout<<",";}std::cout<<"[";for(size_t k=0;k<12;k++){if(k){std::cout<<",";}std::cout<<per_engine_io[i][k];}std::cout<<"]";}
        std::cout<<"],\"count\":"<<count<<",\"jobs\":"<<jobs;
    }
    std::cout<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
