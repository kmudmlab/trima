#include <algorithm>
#include <array>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#define COUNTERS 1
#define TRISC_ON 0
#define STRESS 0
#define CHANNEL (cpu_id%2)
#if FAMILY == 1
#define PAGE_BYTES 1024
#else
#define PAGE_BYTES 256
#endif
#define PAGE_WORDS (PAGE_BYTES/4)
struct Map {
    int fd; size_t bytes; const uint32_t* data;
    explicit Map(const char* path) {
        fd=open(path,O_RDONLY); if(fd<0) { throw std::runtime_error("open input"); }
        struct stat st{}; if(fstat(fd,&st)) { throw std::runtime_error("stat input"); }
        bytes=st.st_size; data=(const uint32_t*)mmap(nullptr,bytes,PROT_READ,MAP_SHARED,fd,0);
        if(data==MAP_FAILED) { throw std::runtime_error("mmap input"); }
    }
    ~Map() { munmap((void*)data,bytes); close(fd); }
};
uint32_t cpu_id=0,cpu_engines=0,cpu_n=0,cpu_m=0;
#ifndef SOURCE_CONTEXTS
#define SOURCE_CONTEXTS 1
#endif
std::vector<uint32_t> local((SOURCE_CONTEXTS==2?495616:409600)/4),tail_mem(266240/4);
std::array<uint32_t,1024> result{};
const uint32_t* arrays[3]; uint64_t sizes[3];
uint64_t physical_q[3],physical_b[3],physical_w;
uintptr_t get_write_ptr(uint32_t cb) { return (uintptr_t)(cb==2?tail_mem.data():local.data()); }
uint32_t get_common_arg_val_impl(uint32_t arg) {
    switch(arg) { case 0:return 110; case 1:return (cpu_engines+1)/2;
        case 2:return cpu_n;case 3:return cpu_m;case 4:return 1;default:return 0; }
}
template<class T>T get_common_arg_val(uint32_t arg) { return T(get_common_arg_val_impl(arg)); }
uint32_t get_absolute_logical_y() { return 0; }
uint32_t get_absolute_logical_x() { return cpu_id/2; }
void invalidate_l1_cache() {}
void noc_async_read_barrier() { ++physical_w; }
void noc_async_write_barrier() {}
void noc_async_write_tile(uint32_t,int,uintptr_t ptr) { std::memcpy(result.data(),(void*)ptr,4096); }
void copy(uint32_t which,uint64_t lo,uint64_t hi,uintptr_t ptr) {
    auto dst=(uint32_t*)ptr;
    uint64_t end=std::min(hi,sizes[which]);
    if(end>lo) { std::memcpy(dst,arrays[which]+lo,(end-lo)*4); }
    if(hi>end) { std::memset(dst+(end>lo?end-lo:0),0,(hi-std::max(lo,end))*4); }
}
void read_page(uint32_t which,uint32_t page,uintptr_t ptr) {
    ++physical_q[which]; physical_b[which]+=PAGE_BYTES;
    copy(which,uint64_t(page)*PAGE_WORDS,uint64_t(page+1)*PAGE_WORDS,ptr);
}
void range_read(uint32_t which,uint64_t lo,uint64_t hi,uintptr_t ptr) {
    uint64_t a=lo&~uint64_t(15),b=(hi+15)&~uint64_t(15);
    if(b>a) { physical_q[which]+=(b-1)/PAGE_WORDS-a/PAGE_WORDS+1; }
    physical_b[which]+=(b-a)*4; copy(which,a,b,ptr);
}
void row_range_16k(uint32_t lo,uint32_t hi,uintptr_t ptr) {
    uint64_t a=lo&~uint64_t(15),b=(uint64_t(hi)+15)&~uint64_t(15);
    if(b>a) { physical_q[0]+=(b-1)/4096-a/4096+1; }
    physical_b[0]+=(b-a)*4; copy(0,a,b,ptr);
}
#include "host_kernel.hpp"
int main(int argc,char** argv) { try {
    if(argc!=5) { throw std::runtime_error("csr schedule engines output"); }
    Map csr(argv[1]),schedule(argv[2]); cpu_engines=std::stoul(argv[3]);
    cpu_n=csr.data[0];cpu_m=csr.data[1];
    if(csr.bytes!=4ull*(3ull+cpu_n+cpu_m)) { throw std::runtime_error("CSR size"); }
    arrays[0]=csr.data+2;arrays[1]=csr.data+cpu_n+3;arrays[2]=schedule.data;
    sizes[0]=uint64_t(cpu_n)+1;sizes[1]=cpu_m;sizes[2]=schedule.bytes/4;
    std::ofstream out(argv[4]); out<<"{\"engines\":[";
    for(cpu_id=0;cpu_id<cpu_engines;++cpu_id) {
        std::fill(local.begin(),local.end(),0);
        std::fill(std::begin(physical_q),std::end(physical_q),0);
        std::fill(std::begin(physical_b),std::end(physical_b),0);physical_w=0;
        replay_kernel();
        if(result[22]) { throw std::runtime_error("kernel error "+std::to_string(result[22])); }
        auto get=[&](uint32_t word) { return uint64_t(result[word])+(uint64_t(result[word+1])<<32); };
        for(uint32_t w=0;w<3;++w) {
            if(get(360+2*w)!=physical_q[w] || get(366+2*w)!=physical_b[w]) { throw std::runtime_error("physical Q/B counter mismatch"); }
        }
        if(get(54)!=physical_w) { throw std::runtime_error("physical W counter mismatch"); }
        if(cpu_id) { out<<","; }
        out<<"[";
#ifdef REPLAY_IO_ONLY
        out<<"null";
#else
        out<<get(0);
#endif
        out<<","<<get(4)<<","<<get(400)<<","<<get(402);
        for(uint32_t w=0;w<3;++w) { out<<","<<physical_q[w]; }
        for(uint32_t w=0;w<3;++w) { out<<","<<physical_b[w]; }
        out<<","<<physical_w<<"]";
    }
    out<<"],\"fields\":[\"count\",\"candidates\",\"identity1\",\"identity2\",\"rowQ\",\"colQ\",\"scheduleQ\",\"rowB\",\"colB\",\"scheduleB\",\"W\"]}\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<"\n";return 1; } }
