#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
int main(int argc,char**argv){try{
 if(argc!=2)throw std::runtime_error("input CSR");std::ifstream f(argv[1],std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("input");uint64_t bytes=f.tellg();f.seekg(0);std::vector<uint32_t>a(bytes/4);f.read((char*)a.data(),bytes);if(!f)throw std::runtime_error("read");uint32_t n=a[0],m=a[1];auto rp=a.data()+2,col=rp+n+1;
 if(a.size()!=uint64_t(n)+m+3||rp[0]||rp[n]!=m)throw std::runtime_error("CSR shape");
 std::vector<uint32_t> mark(n);std::array<uint64_t,220> count{},candidates{};uint64_t hash_keys=0,all_keys=0,hash_tasks=0,all_tasks=0,hp=0,ha=0,hash_rows=0;
 for(uint32_t u=0;u<n;u++){
  uint32_t lo=rp[u],hi=rp[u+1],du=hi-lo;if(hi<lo||hi>m)throw std::runtime_error("row pointer");
  for(uint32_t j=lo;j<hi;j++){uint32_t v=col[j];if(v<=u||v>=n||(j>lo&&v<=col[j-1]))throw std::runtime_error("numeric-forward sorted unique");uint32_t dv=rp[v+1]-rp[v];if(du&&dv){bool hash=std::max(du,dv)>128;uint64_t keys=hash?std::min(du,dv):dv;all_keys+=keys;++all_tasks;if(hash){hash_keys+=keys;++hash_tasks;}}}
  if(du>128){++hash_rows;hp+=du-1;for(uint32_t j=lo+1;j<hi;j++)ha+=col[j]==col[j-1]+1;}
  if(du<2)continue;for(uint32_t j=lo;j<hi;j++)mark[col[j]]=u+1;
  uint32_t maximum=col[hi-1];
  for(uint32_t j=lo;j+1<hi;j++){uint32_t v=col[j];for(uint32_t k=rp[v];k<rp[v+1]&&col[k]<=maximum;k++){++candidates[u%220];count[u%220]+=mark[col[k]]==u+1;}}
 }
 uint64_t total=0;for(auto x:count)total+=x;
 std::cout<<"{\"count\":"<<total<<",\"engine220_counts\":[";for(int i=0;i<220;i++){if(i)std::cout<<",";std::cout<<count[i];}std::cout<<"],\"engine220_effective_candidates\":[";for(int i=0;i<220;i++){if(i)std::cout<<",";std::cout<<candidates[i];}
 std::cout<<"],\"steptc_hash_candidate_keys\":"<<hash_keys<<",\"steptc_all_candidate_keys\":"<<all_keys<<",\"steptc_hash_tasks\":"<<hash_tasks<<",\"steptc_all_tasks\":"<<all_tasks<<",\"hash_rows\":"<<hash_rows<<",\"hash_row_adjacent_pairs\":"<<ha<<",\"hash_row_pairs\":"<<hp<<"}\n";
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
