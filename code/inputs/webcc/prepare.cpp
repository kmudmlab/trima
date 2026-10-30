// Common normalization only; no triangle algorithm or device-specific layout.
#include <algorithm>
#include <parallel/algorithm>
#include <vector>
#include <numeric>
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cassert>
#include <chrono>
#include <array>
#include <omp.h>
using U=uint32_t; using Q=uint64_t;
double now(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
struct Reader {
 std::vector<unsigned char> b=std::vector<unsigned char>(1<<23);size_t p=0,n=0;
 int get(){if(p==n){n=fread(b.data(),1,b.size(),stdin);p=0;if(!n){assert(!ferror(stdin));return EOF;}}return b[p++];}
 bool number(U& v){int c;do{c=get();}while(c!=EOF&&c<=32);if(c==EOF)return false;Q x=0;assert(c>='0'&&c<='9');do{x=x*10+c-'0';assert(x<0x80000000ULL);c=get();}while(c>='0'&&c<='9');assert(c==EOF||c<=32);v=U(x);return true;}
};
int main(int argc,char**argv){
 assert(argc==3);double t=now();Reader in;std::vector<Q>e;e.reserve(strtoull(argv[2],nullptr,10));U a,b,n=0;Q arcs=0,loops=0;
 while(in.number(a)){assert(in.number(b));arcs++;n=std::max(n,std::max(a,b)+1);if(a==b){loops++;continue;}e.push_back((Q(std::min(a,b))<<32)|std::max(a,b));}
 fprintf(stderr,"parsed %llu arcs in %.3fs\n",(unsigned long long)arcs,now()-t);double parsed=now();
 __gnu_parallel::sort(e.begin(),e.end());e.erase(std::unique(e.begin(),e.end()),e.end());assert(e.size()<0x80000000ULL);
 fprintf(stderr,"deduplicated %zu edges in %.3fs\n",e.size(),now()-parsed);double dedup=now();
 std::vector<U>d(n),order,rank(n,~0u);for(Q x:e){d[x>>32]++;d[U(x)]++;}
 for(U u=0;u<n;u++)if(d[u])order.push_back(u);U original_n=n,max_undirected=*std::max_element(d.begin(),d.end());
 __gnu_parallel::sort(order.begin(),order.end(),[&](U x,U y){return d[x]!=d[y]?d[x]<d[y]:x<y;});
 for(U i=0;i<order.size();i++)rank[order[i]]=i;n=order.size();assert(n&&n<0x80000000u);
#pragma omp parallel for schedule(static)
 for(size_t i=0;i<e.size();i++){U x=rank[e[i]>>32],y=rank[U(e[i])];e[i]=(Q(std::min(x,y))<<32)|std::max(x,y);}
 __gnu_parallel::sort(e.begin(),e.end());std::vector<U>().swap(d);std::vector<U>().swap(order);std::vector<U>().swap(rank);
 U m=e.size();std::vector<U>r(size_t(n)+1),c(m);for(size_t j=0;j<e.size();j++){r[(e[j]>>32)+1]++;c[j]=U(e[j]);}std::partial_sum(r.begin(),r.end(),r.begin());std::vector<Q>().swap(e);
 FILE*f=fopen(argv[1],"wb");assert(f);assert(fwrite(&n,4,1,f)==1&&fwrite(&m,4,1,f)==1);assert(fwrite(r.data(),4,r.size(),f)==r.size());assert(fwrite(c.data(),4,c.size(),f)==c.size());assert(fclose(f)==0);
 double prepared=now();fprintf(stderr,"CSR written n=%u m=%u in %.3fs\n",n,m,prepared-t);
 std::vector<U>deg(n);Q W=0,wedges=0,above1=0,above2=0,work1=0,work2=0;std::array<Q,110>wc{};
#pragma omp parallel for reduction(+:W,wedges,above1,above2,work1,work2) schedule(dynamic)
 for(int core=0;core<110;core++)for(Q base=2*core;base<n;base+=220)for(Q u=base;u<std::min(Q(n),base+2);u++){
  U du=r[u+1]-r[u];deg[u]=du;Q w=0;wedges+=Q(du)*(du?du-1:0)/2;
  for(U j=r[u];j<r[u+1];j++){U v=c[j];assert(v>u&&v<n);assert(j==r[u]||v>c[j-1]);w+=r[v+1]-r[v];}
  W+=w;wc[core]+=w;if(du>8208){above1++;work1+=w;}if(du>16416){above2++;work2+=w;}
 }
 __gnu_parallel::sort(deg.begin(),deg.end());
 printf("{\"n\":%u,\"m\":%u,\"raw_arcs\":%llu,\"raw_self_loops\":%llu,\"raw_id_span\":%u,\"max_undirected_degree\":%u,\"max_degree\":%u,\"degree_p50\":%u,\"degree_p90\":%u,\"degree_p99\":%u,\"degree_p999\":%u,\"W\":%llu,\"wedges\":%llu,\"rows_above_8208\":%llu,\"rows_above_16416\":%llu,\"work_above_8208\":%llu,\"work_above_16416\":%llu,\"max_core_W\":%llu,\"prepare_cpu_s\":%.9f,\"parse_s\":%.9f,\"dedup_s\":%.9f,\"orientation_write_s\":%.9f,\"audit_s\":%.9f,\"threads\":%d,\"validated_strict_numeric_orientation\":true}\n",n,m,(unsigned long long)arcs,(unsigned long long)loops,original_n,max_undirected,deg.back(),deg[n/2],deg[size_t(n)*90/100],deg[size_t(n)*99/100],deg[size_t(n)*999/1000],(unsigned long long)W,(unsigned long long)wedges,(unsigned long long)above1,(unsigned long long)above2,(unsigned long long)work1,(unsigned long long)work2,(unsigned long long)*std::max_element(wc.begin(),wc.end()),prepared-t,parsed-t,dedup-parsed,prepared-dedup,now()-prepared,omp_get_max_threads());
}
