// Independent CPU reference: global-ID bitsets and binary-search intersections.
// Validation only: neither this time nor this auxiliary memory is benchmarked.
#include <algorithm>
#include <array>
#include <vector>
#include <cstdint>
#include <cstdio>
#include <cassert>
#include <chrono>
#include <omp.h>
using U=uint32_t;using Q=uint64_t;
int main(int argc,char**argv){
 assert(argc==2);auto start=std::chrono::steady_clock::now();FILE*f=fopen(argv[1],"rb");assert(f);U n,m;assert(fread(&n,4,1,f)==1&&fread(&m,4,1,f)==1);std::vector<U>r(size_t(n)+1),c(m);assert(fread(r.data(),4,r.size(),f)==r.size()&&fread(c.data(),4,c.size(),f)==c.size());assert(fgetc(f)==EOF);fclose(f);assert(r[0]==0&&r[n]==m);std::array<Q,110>counts{};
#pragma omp parallel
 {
  std::vector<Q>bits((size_t(n)+63)/64);
#pragma omp for schedule(dynamic,1)
  for(int core=0;core<110;core++){
   Q count=0;
   for(Q base=core*2;base<n;base+=220)for(Q u=base;u<std::min(Q(n),base+2);u++){
    U lo=r[u],hi=r[u+1];assert(lo<=hi);for(U j=lo;j<hi;j++){assert(c[j]>u&&c[j]<n);assert(j==lo||c[j]>c[j-1]);}
    if(hi-lo<2)continue;
    for(U j=lo;j<hi;j++)bits[c[j]/64]|=Q(1)<<(c[j]%64);
    for(U j=lo;j+1<hi;j++){
     U v=c[j],a=r[v],b=r[v+1];if(a==b||c[a]>c[hi-1]||c[b-1]<c[j+1])continue;
     a=std::lower_bound(c.begin()+a,c.begin()+b,c[j+1])-c.begin();b=std::upper_bound(c.begin()+a,c.begin()+b,c[hi-1])-c.begin();
     if(Q(b-a)>8*Q(hi-j-1)){
      for(U k=j+1;k<hi&&a<b;k++){a=std::lower_bound(c.begin()+a,c.begin()+b,c[k])-c.begin();if(a<b&&c[a]==c[k]){count++;a++;}}
     }else for(U k=a;k<b;k++)count+=(bits[c[k]/64]>>(c[k]%64))&1;
    }
    for(U j=lo;j<hi;j++)bits[c[j]/64]=0;
   }
   counts[core]=count;fprintf(stderr,"core %d: %llu\n",core,(unsigned long long)count);
  }
 }
 Q count=0;for(Q v:counts)count+=v;
 printf("{\"count\":%llu,\"engine_counts\":[",(unsigned long long)count);for(int i=0;i<110;i++)printf("%s%llu",i?",":"",(unsigned long long)counts[i]);printf("],\"reference_cpu_s\":%.9f,\"threads\":%d}\n",std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count(),omp_get_max_threads());
}
