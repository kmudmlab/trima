#include <algorithm>
#include <numeric>
#include <vector>
#include <fstream>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cassert>
#include <chrono>
#include <string>
using U=uint32_t;using Q=uint64_t;
int main(int argc,char**argv){
 assert(argc==4);auto t=std::chrono::steady_clock::now();std::vector<Q> edges;U n=0;
 if(std::string(argv[1])=="text"){
  FILE*f=fopen(argv[2],"r");assert(f);char*line=nullptr;size_t cap=0;while(getline(&line,&cap,f)>0){if(line[0]=='#'||line[0]=='%')continue;unsigned a,b;if(sscanf(line,"%u %u",&a,&b)!=2)continue;n=std::max(n,std::max(a,b)+1);if(a!=b)edges.push_back((Q(std::min(a,b))<<32)|std::max(a,b));}free(line);fclose(f);
 }else{
  FILE*f=fopen(argv[2],"rb");assert(f);U m;assert(fread(&n,4,1,f)==1);assert(fread(&m,4,1,f)==1);std::vector<U> r(size_t(n)+1),c(m);assert(fread(r.data(),4,r.size(),f)==r.size());assert(fread(c.data(),4,c.size(),f)==c.size());fclose(f);for(U u=0;u<n;u++)for(U j=r[u];j<r[u+1];j++){U v=c[j];assert(v<n);if(u!=v)edges.push_back((Q(std::min(u,v))<<32)|std::max(u,v));}
 }
 std::sort(edges.begin(),edges.end());edges.erase(std::unique(edges.begin(),edges.end()),edges.end());assert(edges.size()<0x80000000ULL);
 std::vector<U> d(n),order,rank(n,~0u);for(Q e:edges){d[e>>32]++;d[U(e)]++;}for(U u=0;u<n;u++)if(d[u])order.push_back(u);std::sort(order.begin(),order.end(),[&](U a,U b){return d[a]!=d[b]?d[a]<d[b]:a<b;});for(U i=0;i<order.size();i++)rank[order[i]]=i;n=order.size();
 for(Q&e:edges){U a=rank[e>>32],b=rank[U(e)];e=(Q(std::min(a,b))<<32)|std::max(a,b);}std::sort(edges.begin(),edges.end());U m=edges.size();std::vector<U> r(size_t(n)+1),c(m);for(size_t i=0;i<edges.size();i++){r[(edges[i]>>32)+1]++;c[i]=U(edges[i]);}std::partial_sum(r.begin(),r.end(),r.begin());
 FILE*f=fopen(argv[3],"wb");assert(f);assert(fwrite(&n,4,1,f)==1);assert(fwrite(&m,4,1,f)==1);assert(fwrite(r.data(),4,r.size(),f)==r.size());assert(fwrite(c.data(),4,c.size(),f)==c.size());fclose(f);
 double prep=std::chrono::duration<double>(std::chrono::steady_clock::now()-t).count();Q count=0,W=0;std::vector<Q> wc(110),cc(110);std::vector<U> deg(n);for(U u=0;u<n;u++){deg[u]=r[u+1]-r[u];for(U j=r[u];j<r[u+1];j++){U v=c[j];assert(v>u);assert(j==r[u]||c[j]>c[j-1]);Q w=r[v+1]-r[v];W+=w;wc[(u/2)%110]+=w;U a=j+1,b=r[v];while(a<r[u+1]&&b<r[v+1]){if(c[a]<c[b])a++;else if(c[b]<c[a])b++;else{count++;cc[(u/2)%110]++;a++;b++;}}}}
 std::sort(deg.begin(),deg.end());printf("{\"n\":%u,\"m\":%u,\"count\":%llu,\"W\":%llu,\"max_degree\":%u,\"degree_p50\":%u,\"degree_p90\":%u,\"degree_p99\":%u,\"degree_p999\":%u,\"max_core_W\":%llu,\"prepare_cpu_s\":%.9f,\"validated_strict_numeric_orientation\":true,\"engine_counts\":[",n,m,(unsigned long long)count,(unsigned long long)W,deg.back(),deg[n/2],deg[size_t(n)*90/100],deg[size_t(n)*99/100],deg[size_t(n)*999/1000],(unsigned long long)*std::max_element(wc.begin(),wc.end()),prep);for(U i=0;i<110;i++)printf("%s%llu",i?",":"",(unsigned long long)cc[i]);puts("]}");
}
