#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
int main(int argc,char** argv){try{
 if(argc!=2){throw std::runtime_error("oracle input.csr");}
 std::ifstream f(argv[1],std::ios::binary);uint32_t n,m;
 f.read(reinterpret_cast<char*>(&n),4);f.read(reinterpret_cast<char*>(&m),4);
 std::vector<uint32_t> rp(n+1),c(m);f.read(reinterpret_cast<char*>(rp.data()),4ull*(n+1));f.read(reinterpret_cast<char*>(c.data()),4ull*m);
 if(!f||rp.front()!=0||rp.back()!=m){throw std::runtime_error("invalid CSR");}
 uint64_t by_merge=0,by_wedge=0;
 for(uint32_t u=0;u<n;u++){
  if(rp[u]>rp[u+1]){throw std::runtime_error("offset order");}
  for(uint32_t e=rp[u];e<rp[u+1];e++){
   uint32_t v=c[e];if(v<=u||v>=n||(e>rp[u]&&c[e-1]>=v)){throw std::runtime_error("orientation/order");}
   uint32_t i=rp[u],j=rp[v];
   while(i<rp[u+1]&&j<rp[v+1]){
    uint32_t a=c[i],b=c[j];if(a==b){++by_merge;}if(a<=b){++i;}if(a>=b){++j;}
   }
   for(uint32_t k=e+1;k<rp[u+1];k++){
    by_wedge+=std::binary_search(c.begin()+rp[v],c.begin()+rp[v+1],c[k]);
   }
  }
 }
 if(by_merge!=by_wedge){throw std::runtime_error("independent counts disagree");}
 std::cout<<"{\"merge_count\":"<<by_merge<<",\"wedge_count\":"<<by_wedge<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
