#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <iomanip>
#include <vector>
#include <stdexcept>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <zlib.h>
struct Bin {
 uint64_t rows=0,pairs=0,consecutive=0,degree_equal_pairs=0,same_degree_consecutive=0,very_consecutive=0;
 long double rho=0,span=0,c=0;
 void add(double x,double y,double z,uint64_t p,uint64_t a,uint64_t e,uint64_t s){++rows;rho+=x;span+=y;c+=z;pairs+=p;consecutive+=a;degree_equal_pairs+=e;same_degree_consecutive+=s;very_consecutive+=z>=.9;}
 void print(){std::cout<<"{\"rows\":"<<rows<<",\"pairs\":"<<pairs<<",\"consecutive\":"<<consecutive<<",\"degree_equal_pairs\":"<<degree_equal_pairs<<",\"same_degree_consecutive\":"<<same_degree_consecutive<<",\"rows_consecutive_ge_0_9\":"<<very_consecutive<<",\"sum_rho\":"<<double(rho)<<",\"sum_span_ratio\":"<<double(span)<<",\"sum_consecutive_ratio\":"<<double(c)<<"}";}
};
struct Corr {
 uint64_t n=0;long double x=0,y=0,xx=0,yy=0,xy=0;
 void add(double a,double b){++n;x+=a;y+=b;xx+=a*a;yy+=b*b;xy+=a*b;}
 void print(){long double den=(n*xx-x*x)*(n*yy-y*y);if(n<2||den<=0){std::cout<<"null";}else{std::cout<<double((n*xy-x*y)/sqrtl(den));}}
};
int main(int argc,char**argv){try{
 if(argc!=3){throw std::runtime_error("density input.csr rows.csv.gz");}
 int fd=open(argv[1],O_RDONLY);struct stat st;if(fd<0||fstat(fd,&st)){throw std::runtime_error("input");}
 auto data=(const uint32_t*)mmap(nullptr,st.st_size,PROT_READ,MAP_PRIVATE,fd,0);if(data==MAP_FAILED){throw std::runtime_error("mmap");}
 uint32_t n=data[0],m=data[1];auto rp=data+2,col=rp+n+1;
 if(!n||uint64_t(st.st_size)!=4ull*(uint64_t(n)+m+3)||rp[0]||rp[n]!=m){throw std::runtime_error("CSR size");}
 std::vector<uint32_t> deg(n);std::vector<uint8_t> active(n);
 for(uint32_t u=0;u<n;u++){
  if(rp[u]>rp[u+1]||rp[u+1]>m){throw std::runtime_error("offsets");}
  uint32_t du=rp[u+1]-rp[u];deg[u]+=du;
  for(uint32_t j=rp[u];j<rp[u+1];j++){
   uint32_t v=col[j];if(v<=u||v>=n||(j>rp[u]&&col[j-1]>=v)){throw std::runtime_error("forward");}++deg[v];uint32_t dv=rp[v+1]-rp[v];
   if(du&&dv&&std::max(du,dv)>128){active[du>dv||(du==dv&&u>v)?u:v]=1;}
  }
 }
 double rb[]={.0001,.001,.01,.1,.25,.5,.75,.9,1.00000001},sb[]={1.00000001,1.1,2,4,16,64,256,1024,1e100};
 Bin total,actual,rbins[9],sbins[9],joint[9][9];Corr rc,lc,sc;
 std::vector<double> rhos,spans,cs;uint64_t dense_lowc=0,highc_lowrho=0,highc_dense=0,highc_local=0;
 gzFile out=gzopen(argv[2],"wb1");if(!out){throw std::runtime_error("output");}gzbuffer(out,1<<20);
 gzprintf(out,"rank,forward_degree,undirected_degree,tail_vertices,rho,span_per_neighbor,consecutive_ratio,consecutive_pairs,degree_equal_pairs,same_degree_consecutive_pairs,steptc_actual_hash_row\n");
 for(uint32_t u=0;u<n;u++){
  uint32_t lo=rp[u],hi=rp[u+1],d=hi-lo;if(d<=128){continue;}
  uint64_t cons=0,eq=0,same=0;
  for(uint32_t j=lo+1;j<hi;j++){bool e=deg[col[j]]==deg[col[j-1]],c=col[j]==col[j-1]+1;eq+=e;cons+=c;same+=e&&c;}
  double rho=double(d)/(n-u),span=double(uint64_t(col[hi-1])-col[lo]+1)/d,c=double(cons)/(d-1);
  int ri=std::lower_bound(rb,rb+9,rho)-rb,si=std::lower_bound(sb,sb+9,span)-sb;if(ri>=9||si>=9){throw std::runtime_error("bin");}
  total.add(rho,span,c,d-1,cons,eq,same);if(active[u]){actual.add(rho,span,c,d-1,cons,eq,same);}
  rbins[ri].add(rho,span,c,d-1,cons,eq,same);sbins[si].add(rho,span,c,d-1,cons,eq,same);joint[ri][si].add(rho,span,c,d-1,cons,eq,same);
  rc.add(rho,c);lc.add(log10(rho),c);sc.add(log10(span),c);rhos.push_back(rho);spans.push_back(span);cs.push_back(c);
  dense_lowc+=rho>=.5&&c<.9;highc_lowrho+=c>=.9&&rho<.01;highc_dense+=c>=.9&&rho>=.5;highc_local+=c>=.9&&span<=1.1;
  if(gzprintf(out,"%u,%u,%u,%u,%.12g,%.12g,%.12g,%llu,%llu,%llu,%u\n",u,d,deg[u],n-u,rho,span,c,(unsigned long long)cons,(unsigned long long)eq,(unsigned long long)same,unsigned(active[u]))<=0){throw std::runtime_error("write");}
 }
 if(gzclose(out)!=Z_OK){throw std::runtime_error("gzip close");}
 auto quantiles=[](std::vector<double>&v){std::sort(v.begin(),v.end());std::cout<<"[";bool first=true;for(double q:{0.,.5,.9,.99,1.}){if(!first){std::cout<<",";}first=false;if(v.empty()){std::cout<<"null";}else{std::cout<<v[size_t(q*(v.size()-1))];}}std::cout<<"]";};
 std::cout<<std::setprecision(12)<<"{\"n\":"<<n<<",\"m\":"<<m<<",\"all_degree_gt_128\":";total.print();std::cout<<",\"actual_steptc_hash\":";actual.print();
 std::cout<<",\"rho_quantiles_min_p50_p90_p99_max\":";quantiles(rhos);std::cout<<",\"span_quantiles_min_p50_p90_p99_max\":";quantiles(spans);std::cout<<",\"consecutive_quantiles_min_p50_p90_p99_max\":";quantiles(cs);
 std::cout<<",\"pearson_rho_consecutive\":";rc.print();std::cout<<",\"pearson_logrho_consecutive\":";lc.print();std::cout<<",\"pearson_logspan_consecutive\":";sc.print();
 std::cout<<",\"high_consecutive_low_rho_rows\":"<<highc_lowrho<<",\"high_consecutive_dense_tail_rows\":"<<highc_dense<<",\"high_consecutive_compact_span_rows\":"<<highc_local<<",\"dense_tail_but_consecutive_lt_0_9_rows\":"<<dense_lowc;
 std::cout<<",\"rho_bin_upper\":[0.0001,0.001,0.01,0.1,0.25,0.5,0.75,0.9,1],\"span_bin_upper\":[1,1.1,2,4,16,64,256,1024,null],\"rho_bins\":[";
 for(int i=0;i<9;i++){if(i){std::cout<<",";}rbins[i].print();}std::cout<<"],\"span_bins\":[";for(int i=0;i<9;i++){if(i){std::cout<<",";}sbins[i].print();}
 std::cout<<"],\"joint_bins\":[";for(int i=0;i<9;i++){if(i){std::cout<<",";}std::cout<<"[";for(int j=0;j<9;j++){if(j){std::cout<<",";}joint[i][j].print();}std::cout<<"]";}std::cout<<"]}\n";
 munmap((void*)data,st.st_size);close(fd);
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
