#include "tricount.h"
#include <algorithm>
#include <fstream>
#include <vector>
#include <stdexcept>
#include <chrono>
int main(int argc,char**argv){try{
    if(argc!=3)throw std::runtime_error("driver canonical.csr expected");
    std::ifstream f(argv[1],std::ios::binary);uint32_t n,m;f.read((char*)&n,4);f.read((char*)&m,4);
    if(!f||!n||m>0x3fffffffu)throw std::runtime_error("dimensions");
    std::vector<uint32_t> r(n+1),c(m);f.read((char*)r.data(),r.size()*4);f.read((char*)c.data(),c.size()*4);
    if(!f||r[0]||r[n]!=m)throw std::runtime_error("CSR");
    std::vector<std::vector<uint32_t>> rows(n);
    for(uint32_t u=0;u<n;u++)for(uint32_t e=r[u];e<r[u+1];e++){
        uint32_t v=c[e];if(v<=u||v>=n)throw std::runtime_error("not simple forward CSR");rows[u].push_back(v);rows[v].push_back(u);
    }
    std::vector<uint32_t> rp(n+1),col;col.reserve(2*m);
    for(uint32_t u=0;u<n;u++){std::sort(rows[u].begin(),rows[u].end());col.insert(col.end(),rows[u].begin(),rows[u].end());rp[u+1]=col.size();}
    initGPU(col.size(),n,0);auto start=std::chrono::steady_clock::now();
    auto count=tricount(1,col.size(),n,col.data(),rp.data());
    double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::cout<<"{\"count\":"<<count<<",\"upstream_function_s\":"<<seconds<<"}\n";
    if(count!=std::stoull(argv[2]))throw std::runtime_error("independent expected mismatch");
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
