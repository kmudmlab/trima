#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
constexpr uint32_t SIZE=16384,MASK=SIZE-1;
uint32_t av(uint32_t x){x^=x>>16;x*=0x7feb352d;x^=x>>15;x*=0x846ca68b;return x^(x>>16);}
uint32_t slot(uint32_t y,int kind){
 if(kind==0){return y&MASK;}if(kind==1){return (y^(y>>16))&MASK;}
 if(kind==2){return uint32_t(y*0x9E3779B1u)>>(32-14);}return av(y)&MASK;
}
struct Stat {
 uint64_t n=0,sum=0,max=0;
 void add(uint64_t x){++n;sum+=x;max=std::max(max,x);}
 void print(){std::cout<<"{\"n\":"<<n<<",\"sum\":"<<sum<<",\"max\":"<<max<<"}";}
};
struct Pop {
 uint64_t rows=0,keys=0,pairs=0,consecutive=0,same_degree_pairs=0,runs=0,same_degree_runs=0;
 std::vector<uint64_t> histogram=std::vector<uint64_t>(SIZE);
 std::vector<uint32_t> sample;
 std::mt19937_64 rng;
 Pop(uint64_t seed):rng(seed){}
 void offer(uint32_t u,uint32_t d,uint32_t limit){
  if(d>=SIZE){throw std::runtime_error("hash capacity");}
  ++rows;keys+=d;++histogram[d];
  if(sample.size()<limit){sample.push_back(u);}else{uint64_t k=std::uniform_int_distribution<uint64_t>(0,rows-1)(rng);if(k<limit){sample[k]=u;}}
 }
 void adjacency(uint32_t lo,uint32_t hi,const uint32_t* col,const std::vector<uint32_t>& deg){
  uint32_t len=1;bool same=true;
  for(uint32_t j=lo+1;j<hi;j++){
   ++pairs;
   if(col[j]==col[j-1]+1){++consecutive;++len;bool eq=deg[col[j]]==deg[col[j-1]];same_degree_pairs+=eq;same=same&&eq;}
   else{if(len>=2){++runs;same_degree_runs+=same;}len=1;same=true;}
  }
  if(len>=2){++runs;same_degree_runs+=same;}
 }
 void print(){
  std::cout<<"{\"rows\":"<<rows<<",\"keys\":"<<keys<<",\"pairs\":"<<pairs<<",\"consecutive_pairs\":"<<consecutive
   <<",\"same_degree_consecutive_pairs\":"<<same_degree_pairs<<",\"consecutive_runs\":"<<runs<<",\"single_degree_runs\":"<<same_degree_runs<<",\"degree_histogram\":[";
  bool first=true;for(uint32_t i=0;i<SIZE;i++){if(histogram[i]){if(!first){std::cout<<",";}first=false;std::cout<<"["<<i<<","<<histogram[i]<<"]";}}
  std::cout<<"],\"sampled_rows\":"<<sample.size()<<"}";
 }
};
int main(int argc,char**argv){try{
 if(argc!=4){throw std::runtime_error("compare input.csr sample_rows rows.jsonl");}
 int fd=open(argv[1],O_RDONLY);struct stat st;if(fd<0||fstat(fd,&st)){throw std::runtime_error("input");}
 const uint32_t* data=(const uint32_t*)mmap(nullptr,st.st_size,PROT_READ,MAP_PRIVATE,fd,0);
 if(data==MAP_FAILED){throw std::runtime_error("mmap");}
 uint32_t n=data[0],m=data[1],limit=std::stoul(argv[2]);const uint32_t* rp=data+2,*col=rp+n+1;
 if(!n||uint64_t(st.st_size)!=4ull*(uint64_t(n)+m+3)||rp[0]||rp[n]!=m){throw std::runtime_error("CSR dimensions");}
 std::vector<uint32_t> deg(n);std::vector<uint8_t> active(n);
 auto owner=[&](uint32_t u,uint32_t v){uint32_t du=rp[u+1]-rp[u],dv=rp[v+1]-rp[v];
  if(!du||!dv){return n;}if(std::max(du,dv)<=128){return u;}return du>dv||(du==dv&&u>v)?u:v;};
 for(uint32_t u=0;u<n;u++){
  if(rp[u]>rp[u+1]||rp[u+1]>m){throw std::runtime_error("offsets");}
  deg[u]+=rp[u+1]-rp[u];
  for(uint32_t j=rp[u];j<rp[u+1];j++){
   uint32_t v=col[j];if(v<=u||v>=n||(j>rp[u]&&col[j-1]>=v)){throw std::runtime_error("orientation/order");}
   ++deg[v];uint32_t o=owner(u,v);if(o<n){active[o]=1;}
  }
 }
 Pop pop[2]={Pop(20261022),Pop(20261023)};
 uint64_t degree_order_inversions=0;
 for(uint32_t u=0;u<n;u++){
  if(u&&deg[u]<deg[u-1]){++degree_order_inversions;}
  uint32_t d=rp[u+1]-rp[u];
  if(d>128&&active[u]){pop[0].offer(u,d,limit);pop[0].adjacency(rp[u],rp[u+1],col,deg);}
  if(d>=2){pop[1].offer(u,d,limit);pop[1].adjacency(rp[u],rp[u+1],col,deg);}
 }
 std::vector<int32_t> selected(n,-1);
 std::vector<std::vector<uint32_t>> targets(pop[0].sample.size());
 for(uint32_t k=0;k<pop[0].sample.size();k++){selected[pop[0].sample[k]]=k;}
 for(uint32_t u=0;u<n;u++){
  for(uint32_t j=rp[u];j<rp[u+1];j++){
   uint32_t v=col[j],o=owner(u,v);if(o<n&&selected[o]>=0){targets[selected[o]].push_back(o==u?v:u);}
  }
 }
 std::ofstream rowout(argv[3]);if(!rowout){throw std::runtime_error("row output");}
 std::array<std::array<std::array<Stat,4>,4>,2> stats; // family, hash, all-key hit/actual hit/actual miss/uniform miss
 std::vector<uint32_t> table(SIZE);uint64_t candidate_totals[2]={};
 for(int family=0;family<2;family++){
  for(uint32_t k=0;k<pop[family].sample.size();k++){
   uint32_t u=pop[family].sample[k],lo=rp[u],hi=rp[u+1],maximum=col[hi-1];
   std::vector<uint32_t> ts=family?std::vector<uint32_t>(col+lo,col+hi-1):targets[k];std::sort(ts.begin(),ts.end());
   std::vector<uint64_t> prefix(1,0);
   for(uint32_t v:ts){uint32_t end=family?std::upper_bound(col+rp[v],col+rp[v+1],maximum)-col:rp[v+1];prefix.push_back(prefix.back()+end-rp[v]);}
   candidate_totals[family]+=prefix.back();
   std::vector<uint32_t> queries,absent;std::mt19937_64 rng(20261022ull+uint64_t(u)*2+family);
   if(prefix.back()<=1024){for(uint32_t v:ts){uint32_t end=family?std::upper_bound(col+rp[v],col+rp[v+1],maximum)-col:rp[v+1];queries.insert(queries.end(),col+rp[v],col+end);}}
   else{for(int q=0;q<1024;q++){uint64_t ix=std::uniform_int_distribution<uint64_t>(0,prefix.back()-1)(rng);uint32_t ti=std::upper_bound(prefix.begin(),prefix.end(),ix)-prefix.begin()-1;queries.push_back(col[rp[ts[ti]]+ix-prefix[ti]]);}}
   for(int q=0;q<128;q++){uint32_t y;do{y=std::uniform_int_distribution<uint32_t>(0,n-1)(rng);}while(std::binary_search(col+lo,col+hi,y));absent.push_back(y);}
   rowout<<"{\"family\":\""<<(family?"trust-B2":"steptc-D2")<<"\",\"row\":"<<u<<",\"degree\":"<<hi-lo<<",\"candidate_population\":"<<prefix.back()<<",\"sampled_candidates\":"<<queries.size()<<"}\n";
   for(int kind=0;kind<4;kind++){
    std::fill(table.begin(),table.end(),0);
    for(uint32_t j=lo;j<hi;j++){uint32_t y=col[j],s=slot(y,kind);while(table[s]){s=(s+1)&MASK;}table[s]=y+1;}
    auto probe=[&](uint32_t y){uint32_t s=slot(y,kind),steps=1;while(table[s]&&table[s]!=y+1){s=(s+1)&MASK;if(++steps>SIZE){throw std::runtime_error("probe loop");}}return std::make_pair(steps,table[s]==y+1);};
    for(uint32_t j=lo;j<hi;j++){auto p=probe(col[j]);if(!p.second){throw std::runtime_error("missing inserted key");}stats[family][kind][0].add(p.first);}
    for(uint32_t y:queries){auto p=probe(y);if(p.second!=std::binary_search(col+lo,col+hi,y)){throw std::runtime_error("lookup mismatch");}stats[family][kind][p.second?1:2].add(p.first);}
    for(uint32_t y:absent){auto p=probe(y);if(p.second){throw std::runtime_error("absent hit");}stats[family][kind][3].add(p.first);}
   }
  }
 }
 std::cout<<"{\"n\":"<<n<<",\"m\":"<<m<<",\"degree_order_inversions\":"<<degree_order_inversions<<",\"table_size\":16384,\"sample_limit\":"<<limit<<",\"families\":[";
 const char* names[]={"identity","xor_fold","multiply_shift","avalanche"};const char* fields[]={"inserted_success","actual_success","actual_unsuccess","uniform_unsuccess"};
 for(int f=0;f<2;f++){
  if(f){std::cout<<",";}std::cout<<"{\"family\":\""<<(f?"trust-B2":"steptc-D2")<<"\",\"population\":";pop[f].print();
  std::cout<<",\"candidate_population_sampled_rows\":"<<candidate_totals[f]<<",\"hashes\":[";
  for(int h=0;h<4;h++){if(h){std::cout<<",";}std::cout<<"{\"slot\":\""<<names[h]<<"\"";for(int j=0;j<4;j++){std::cout<<",\""<<fields[j]<<"\":";stats[f][h][j].print();}std::cout<<"}";}std::cout<<"]}";
 }
 std::cout<<"]}\n";munmap((void*)data,st.st_size);close(fd);
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
