#include <algorithm>
#include <cstdint>
#include <iostream>
#include <vector>
#include <stdexcept>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
struct Map {
    int fd;size_t bytes;const uint32_t* data;
    explicit Map(const char*p){fd=open(p,O_RDONLY);if(fd<0){throw std::runtime_error("open");}struct stat st{};if(fstat(fd,&st)){throw std::runtime_error("stat");}bytes=st.st_size;data=static_cast<const uint32_t*>(mmap(nullptr,bytes,PROT_READ,MAP_SHARED,fd,0));if(data==MAP_FAILED){throw std::runtime_error("mmap");}}
    ~Map(){munmap(const_cast<uint32_t*>(data),bytes);close(fd);}
};
uint64_t sum1(uint64_t n){return n*(n-1)/2;}
uint64_t sum2(uint64_t n){return n*(n-1)*(2*n-1)/6;}
int main(int argc,char**argv){
    if(argc!=6){return 2;}
    Map csr(argv[1]),aux(argv[2]),mp(argv[3]);uint32_t engines=std::stoul(argv[4]),family=std::stoul(argv[5]);
    uint32_t n=csr.data[0],m=csr.data[1];auto rp=csr.data+2,col=rp+n+1;
    std::vector<uint64_t> q(engines),h1(engines),h2(engines);
    if(family==2){
        uint64_t global=0;
        for(uint32_t u=0;u<n;u++){
            uint32_t degree=rp[u+1]-rp[u];
            for(uint32_t j=0;j+1<degree;j++){
                for(uint32_t k=j+1;k<degree;){
                    uint32_t take=std::min(uint64_t(degree-k),127-global%127);uint32_t e=(global/127)%engines;
                    uint64_t end=uint64_t(k)+take;
                    q[e]+=take;h1[e]+=uint64_t(take)*((uint64_t(u)+1)*0x9e3779b1ull+(uint64_t(j)+1)*0x85ebca6bull)+sum1(end)-sum1(k);
                    h2[e]+=uint64_t(take)*(uint64_t(u)+1)*(uint64_t(j)+1)+sum2(end)-sum2(k);
                    k+=take;global+=take;
                }
            }
            uint64_t want=uint64_t(aux.data[2ull*(u+1)])+(uint64_t(aux.data[2ull*(u+1)+1])<<32);
            if(global!=want){throw std::runtime_error("prefix mismatch");}
        }
    }else{
        for(uint32_t e=0;e<m;e++){
            uint32_t u=aux.data[e],v=col[e],owner=(e/32)%engines;
            if(mp.data[2ull*e]!=rp[v]||mp.data[2ull*e+1]!=rp[v+1]){throw std::runtime_error("M mismatch");}
            auto lr=col+rp[u],sr=col+rp[v];uint32_t length=rp[u+1]-rp[u],slen=rp[v+1]-rp[v];
            if(length<slen){std::swap(lr,sr);std::swap(length,slen);}if(!length||!slen){continue;}
            uint64_t lo=std::lower_bound(sr,sr+slen,lr[0])-sr,hi=std::upper_bound(sr,sr+slen,lr[length-1])-sr,len=hi-lo;
            q[owner]+=len;h1[owner]+=len*(uint64_t(e)+1)*0x9e3779b1ull+sum1(hi)-sum1(lo);
            h2[owner]+=len*(uint64_t(u)+1)*(uint64_t(e)+1)+sum2(hi)-sum2(lo);
        }
    }
    std::cout<<"{\"engines\":[";for(uint32_t e=0;e<engines;e++){if(e){std::cout<<",";}std::cout<<"["<<q[e]<<","<<h1[e]<<","<<h2[e]<<"]";}std::cout<<"]}\n";
}
