// Author kernels; host adapter uses the previously validated degree-oriented CSR.
#include <cuda_runtime.h>
#include <algorithm>
#include <vector>
#include <numeric>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cassert>
#include <cstdint>
#include <cmath>
using index_t=long; using vertex_t=int;
struct Edge { int A,B; };
#define max_thd 256
#define max_block 256
#define GPU_PER_PART 1
#ifdef TRUST
#include "trust_kernel.cuh"
#else
#include "tricore_kernel.cuh"
#endif
#define CK(x) do { cudaError_t e=(x); if(e!=cudaSuccess){fprintf(stderr,"%s:%d %s\n",__FILE__,__LINE__,cudaGetErrorString(e));exit(2);} }while(0)
double now(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
template<class T> T* alloc(size_t n){T* p;CK(cudaMalloc(&p,n*sizeof(T)));return p;}
template<class T> void upload(T* p,const T* h,size_t n){CK(cudaMemcpy(p,h,n*sizeof(T),cudaMemcpyHostToDevice));}
struct Graph { uint32_t n,m; std::vector<long> row; std::vector<int> col; };
Graph read(const char* path){
  FILE* f=fopen(path,"rb");assert(f);Graph g;
  assert(fread(&g.n,4,1,f)==1 && fread(&g.m,4,1,f)==1);
  assert(g.n<INT32_MAX && g.m<INT32_MAX);
  std::vector<uint32_t> row(size_t(g.n)+1);g.row.resize(size_t(g.n)+1);g.col.resize(g.m);
  assert(fread(row.data(),4,row.size(),f)==row.size());
  assert(fread(g.col.data(),4,g.m,f)==g.m);assert(fgetc(f)==EOF);fclose(f);
  std::copy(row.begin(),row.end(),g.row.begin());assert(g.row[0]==0 && g.row[g.n]==g.m);
  for(uint32_t u=0;u<g.n;u++){assert(g.row[u]<=g.row[u+1]);for(long j=g.row[u];j<g.row[u+1];j++){
    assert(g.col[j]>(int)u && g.col[j]<(int)g.n);if(j>g.row[u])assert(g.col[j-1]<g.col[j]);}}
  return g;
}
// TRUST: decreasing forward degree, then neighbor-first reassignment within
// >100, [2,100], <2 degree groups, following preprocess_outdegree.cpp.
// Input orientation is shared with WeTriC; deterministic ID breaks degree ties.
void reorder(Graph& g){
  std::vector<int> order(g.n),inverse(g.n),id(g.n,-1);std::iota(order.begin(),order.end(),0);
  auto degree=[&](int u){return g.row[u+1]-g.row[u];};
  std::sort(order.begin(),order.end(),[&](int a,int b){return degree(a)!=degree(b)?degree(a)>degree(b):a<b;});
  for(int i=0;i<(int)g.n;i++)inverse[order[i]]=i;
  int s2=0,s3=0;while(s2<(int)g.n&&degree(order[s2])>100)s2++;
  s3=s2;while(s3<(int)g.n&&degree(order[s3])>=2)s3++;
  int next[3]={0,s2,s3};
  auto assign=[&](int v){if(id[v]<0)id[v]=next[v<s2?0:v<s3?1:2]++;};
  for(int u:order){if(degree(u)<=2)break;for(long j=g.row[u];j<g.row[u+1];j++)assign(inverse[g.col[j]]);}
  for(int i=0;i<(int)g.n;i++)assign(i);
  assert(next[0]==s2 && next[1]==s3 && next[2]==(int)g.n);
  Graph b;b.n=g.n;b.m=g.m;b.row.resize(size_t(g.n)+1);b.col.resize(g.m);
  for(int i=0;i<(int)g.n;i++)b.row[id[i]+1]=degree(order[i]);
  std::partial_sum(b.row.begin(),b.row.end(),b.row.begin());
  for(int i=0;i<(int)g.n;i++){long p=b.row[id[i]];int u=order[i];
    for(long j=g.row[u];j<g.row[u+1];j++)b.col[p++]=id[inverse[g.col[j]]];}
  g=std::move(b);
  // Kernel overflow path is unsupported in the upstream implementation.
  // Certify that all per-row bins stay below its 99-entry probing threshold.
  int largest=0;std::vector<int> bins(1024);
  for(int u=0;u<(int)g.n;u++){
    long d=degree(u);assert((u<s2&&d>100)||(u>=s2&&u<s3&&d>=2&&d<=100)||(u>=s3&&d<2));
    int mod=d>100?1023:31;std::fill(bins.begin(),bins.end(),0);
    for(long j=g.row[u];j<g.row[u+1];j++)largest=std::max(largest,++bins[g.col[j]&mod]);
  }
  printf("{\"kind\":\"reorder\",\"cta_end\":%d,\"warp_end\":%d,\"max_bin\":%d}\n",s2,s3,largest);
  assert(largest<99);
}
int main(int argc,char** argv){
  assert(argc==4);Graph g=read(argv[1]);unsigned long long expected=strtoull(argv[2],0,10);int reps=atoi(argv[3]);
  double prep=now();
#ifdef TRUST
  reorder(g);const char* method="trust";
#else
  const char* method="tricore";
#endif
  printf("{\"kind\":\"input\",\"method\":\"%s\",\"n\":%u,\"m\":%u,\"reorder_s\":%.9f}\n",method,g.n,g.m,now()-prep);fflush(stdout);
  CK(cudaSetDevice(0));CK(cudaFree(0));
  for(int rep=0;rep<=reps;rep++){
    double full=now(),kernel=0,resident=0;unsigned long long count=0;
    long* dr=alloc<long>(size_t(g.n)+1);int* dc=alloc<int>(g.m);
    upload(dr,g.row.data(),g.row.size());upload(dc,g.col.data(),g.col.size());
    cudaEvent_t a,b;CK(cudaEventCreate(&a));CK(cudaEventCreate(&b));
#ifdef TRUST
    constexpr int blocks=1024,threads=1024;
    int split=0;while(split<(int)g.n && g.row[split+1]-g.row[split]>100)split++;
    int ix[3]={blocks*32,blocks,split+blocks*32};
    int* di=alloc<int>(3);upload(di,ix,3);
    auto counter=alloc<unsigned long long>(1);CK(cudaMemset(counter,0,8));
    int* bins=alloc<int>(size_t(blocks)*1024*100);
    // Upstream profiling arrays are allocated even though instrumentation is off.
    auto gt=alloc<unsigned long long>(size_t(g.n)+1),gc=alloc<unsigned long long>(size_t(g.n)+1);
    CK(cudaDeviceSynchronize());double t=now();CK(cudaEventRecord(a));
    dynamic_assign<<<blocks,threads>>>(dc,dr,g.m,g.n,bins,counter,0,1,100,32,di,1,split,gt,gc);
    CK(cudaGetLastError());CK(cudaEventRecord(b));CK(cudaEventSynchronize(b));
    CK(cudaMemcpy(&count,counter,8,cudaMemcpyDeviceToHost));resident=now()-t;
    float ms;CK(cudaEventElapsedTime(&ms,a,b));kernel=ms/1000.;
    CK(cudaFree(di));CK(cudaFree(counter));CK(cudaFree(bins));CK(cudaFree(gt));CK(cudaFree(gc));
#else
    constexpr long chunk=16777216;
    Edge* de=alloc<Edge>(chunk);long* counts=alloc<long>(256);std::vector<Edge> edges(chunk);
    long offset=0;int u=0;long hostcounts[256];
    while(offset<g.m){long len=std::min(chunk,long(g.m)-offset);
      for(long j=0;j<len;j++){while(g.row[u+1]<=offset+j)u++;edges[j]={u,g.col[offset+j]};}
      upload(de,edges.data(),len);CK(cudaMemset(counts,0,256*sizeof(long)));CK(cudaDeviceSynchronize());
      double t=now();CK(cudaEventRecord(a));
      warp_binary_kernel<<<256,256>>>(de,dc,dr,0,len,counts);
      CK(cudaGetLastError());CK(cudaEventRecord(b));CK(cudaEventSynchronize(b));
      CK(cudaMemcpy(hostcounts,counts,sizeof(hostcounts),cudaMemcpyDeviceToHost));
      for(long c:hostcounts){assert(c>=0);count+=c;}resident+=now()-t;
      float ms;CK(cudaEventElapsedTime(&ms,a,b));kernel+=ms/1000.;offset+=len;
    }
    CK(cudaFree(de));CK(cudaFree(counts));
#endif
    CK(cudaFree(dr));CK(cudaFree(dc));CK(cudaEventDestroy(a));CK(cudaEventDestroy(b));
    printf("{\"kind\":\"sample\",\"method\":\"%s\",\"warmup\":%s,\"count\":%llu,\"kernel_s\":%.9f,\"resident_s\":%.9f,\"full_call_s\":%.9f}\n",method,rep==0?"true":"false",count,kernel,resident,now()-full);fflush(stdout);assert(count==expected);
  }
}
