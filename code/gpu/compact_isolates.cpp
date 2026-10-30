#include <cstdint>
#include <vector>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
int main(int argc,char** argv){try{
 if(argc!=3){throw std::runtime_error("compact input.csr output.csr");}
 int fd=open(argv[1],O_RDONLY);struct stat st;
 if(fd<0||fstat(fd,&st)){throw std::runtime_error("open/stat");}
 auto a=static_cast<const uint32_t*>(mmap(nullptr,st.st_size,PROT_READ,MAP_PRIVATE,fd,0));
 if(a==MAP_FAILED){throw std::runtime_error("mmap");}
 uint32_t n=a[0],m=a[1];auto rp=a+2,col=rp+n+1;
 if(st.st_size!=4ull*(uint64_t(n)+m+3)){throw std::runtime_error("input length");}
 std::vector<uint32_t> map(n,0xffffffffu);uint32_t nn=0;
 for(uint32_t u=0;u<n;u++){
  if(rp[u+1]>rp[u]){map[u]=0;}
  for(uint32_t e=rp[u];e<rp[u+1];e++){
   if(col[e]<=u||col[e]>=n){throw std::runtime_error("not forward");}
   map[col[e]]=0;
  }
 }
 for(uint32_t u=0;u<n;u++){if(map[u]!=0xffffffffu){map[u]=nn++;}}
 int out=open(argv[2],O_CREAT|O_EXCL|O_WRONLY,0600);if(out<0){throw std::runtime_error("output exists/open failed");}
 auto put=[&](const void* p,size_t bytes){const char* q=static_cast<const char*>(p);while(bytes){ssize_t k=write(out,q,bytes);if(k<=0){throw std::runtime_error("write");}q+=k;bytes-=k;}};
 put(&nn,4);put(&m,4);std::vector<uint32_t> buffer;buffer.reserve(1<<20);
 auto flush=[&](){put(buffer.data(),buffer.size()*4);buffer.clear();};
 for(uint32_t u=0;u<n;u++){if(map[u]!=0xffffffffu){buffer.push_back(rp[u]);if(buffer.size()==(1<<20)){flush();}}}
 buffer.push_back(m);flush();
 for(uint32_t e=0;e<m;e++){buffer.push_back(map[col[e]]);if(buffer.size()==(1<<20)){flush();}}
 flush();close(out);munmap(const_cast<uint32_t*>(a),st.st_size);close(fd);
 std::cout<<"{\"old_n\":"<<n<<",\"n\":"<<nn<<",\"m\":"<<m<<",\"removed_isolates\":"<<n-nn<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
