#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <random>
#include <vector>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
static uint32_t avalanche(uint32_t x){x^=x>>16;x*=0x7feb352d;x^=x>>15;x*=0x846ca68b;return x^(x>>16);}
int main(int argc,char** argv){
 if(argc!=3){return 2;}
 int fd=open(argv[1],O_RDONLY);struct stat st;if(fd<0||fstat(fd,&st)){return 3;}
 auto data=(const uint32_t*)mmap(nullptr,st.st_size,PROT_READ,MAP_SHARED,fd,0);
 if(data==MAP_FAILED){return 4;}
 uint32_t n=data[0],m=data[1];const uint32_t* rp=data+2;const uint32_t* col=rp+n+1;
 if(uint64_t(st.st_size)!=4*(uint64_t(n)+m+3)){return 5;}
 std::mt19937 gen(20261022);std::vector<uint32_t> sampled;uint64_t eligible=0;
 for(uint32_t u=0;u<n;u++){
  if(rp[u+1]-rp[u]<=128){continue;}
  ++eligible;
  if(sampled.size()<200){sampled.push_back(u);}
  else{uint64_t j=std::uniform_int_distribution<uint64_t>(0,eligible-1)(gen);if(j<200){sampled[j]=u;}}
 }
 uint64_t adjacent=0,pairs=0,miss_steps[2]={},insert_steps[2]={},queries[2]={};
 std::vector<uint32_t> hash(16384);
 for(uint32_t u:sampled){
  uint32_t lo=rp[u],hi=rp[u+1];if(hi-lo>=hash.size()){return 6;}
  for(uint32_t j=lo+1;j<hi;j++){++pairs;adjacent+=col[j]==col[j-1]+1;}
  std::vector<uint32_t> missing;
  while(missing.size()<128){uint32_t y=gen()%n;if(!std::binary_search(col+lo,col+hi,y)){missing.push_back(y);}}
  for(uint32_t mix=0;mix<2;mix++){
   std::fill(hash.begin(),hash.end(),0);
   for(uint32_t j=lo;j<hi;j++){
    uint32_t y=col[j],slot=(mix?avalanche(y):(y^(y>>16)))&16383;
    while(hash[slot]&&hash[slot]!=y+1){slot=(slot+1)&16383;++insert_steps[mix];}
    hash[slot]=y+1;
   }
   for(uint32_t y:missing){uint32_t slot=(mix?avalanche(y):(y^(y>>16)))&16383;
    while(hash[slot]){slot=(slot+1)&16383;++miss_steps[mix];}++queries[mix];}
  }
 }
 std::cout<<"{\"eligible_rows\":"<<eligible<<",\"sampled_rows\":"<<sampled.size()<<",\"adjacent_id_pairs\":"<<adjacent<<",\"pairs\":"<<pairs<<",\"missing_lookup_steps\":["<<miss_steps[0]<<","<<miss_steps[1]<<"],\"insert_collisions\":["<<insert_steps[0]<<","<<insert_steps[1]<<"],\"missing_queries\":["<<queries[0]<<","<<queries[1]<<"]";
 if(std::stoi(argv[2])){
  std::vector<uint64_t> candidates(220);
  for(uint32_t u=0;u<n;u++){
   uint32_t lo=rp[u],hi=rp[u+1];if(hi-lo<2){continue;}uint32_t maximum=col[hi-1];
   for(uint32_t j=lo;j+1<hi;j++){
    uint32_t v=col[j],a=rp[v],b=rp[v+1];
    candidates[u%220]+=std::upper_bound(col+a,col+b,maximum)-(col+a);
   }
  }
  std::cout<<",\"pruned_engine_candidates\":[";
  for(uint32_t i=0;i<220;i++){if(i){std::cout<<",";}std::cout<<candidates[i];}std::cout<<"]";
 }
 std::cout<<"}\n";munmap((void*)data,st.st_size);close(fd);
}
