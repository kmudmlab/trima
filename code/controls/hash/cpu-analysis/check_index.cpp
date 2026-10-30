#include <zlib.h>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>
#include <stdexcept>
int main(int argc,char**argv){try{
 if(argc!=2){throw std::runtime_error("index.gz");}gzFile f=gzopen(argv[1],"rb");if(!f){throw std::runtime_error("open");}gzbuffer(f,1<<20);
 std::string line,last;uint64_t rows=0,inv=0,idinv=0,gaps=0,lastid=0;std::vector<std::string> examples;
 auto record=[&](){
  auto p=line.rfind('\t');if(p==std::string::npos){throw std::runtime_error("index format");}
  std::string name=line.substr(0,p);char* end;uint64_t id=strtoull(line.c_str()+p+1,&end,10);
  if(*end&&*end!='\r'){throw std::runtime_error("invalid ID");}
  if(rows){if(name<last){++inv;if(examples.size()<5){examples.push_back(last+" -> "+name);}}idinv+=id<=lastid;gaps+=id!=lastid+1;}
  last=name;lastid=id;++rows;line.clear();
 };
 char b[1<<20];int n;
 while((n=gzread(f,b,sizeof(b)))>0){for(int i=0;i<n;i++){if(b[i]=='\n'){record();}else{line.push_back(b[i]);}}}
 if(n<0){throw std::runtime_error("gzip read");}if(!line.empty()){record();}if(gzclose(f)!=Z_OK){throw std::runtime_error("gzip close/CRC");}
 std::cout<<"{\"rows\":"<<rows<<",\"hostname_lexicographic_inversions\":"<<inv<<",\"id_nondecreasing_violations\":"<<idinv<<",\"id_nonconsecutive_pairs\":"<<gaps<<",\"last_id\":"<<lastid<<",\"comparison\":\"bytewise hostname order, no normalization\"}\n";
 for(auto& s:examples){std::cerr<<s<<"\n";}
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
