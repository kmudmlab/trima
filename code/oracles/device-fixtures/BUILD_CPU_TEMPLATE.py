"""검증 전 host 도구 생성. 실패는 build-v1에 기록한다."""
from pathlib import Path
import subprocess,json
P=Path(__file__).resolve().parent;C=P/'code/cpu';O=P/'build-v1';O.mkdir(exist_ok=True)
header=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
using U=uint64_t;
struct CSR {std::vector<uint32_t> raw;uint32_t n,m,*rp,*col;
 explicit CSR(const char*p){std::ifstream f(p,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("input");auto z=f.tellg();f.seekg(0);raw.resize(size_t(z)/4);f.read((char*)raw.data(),z);if(!f)throw std::runtime_error("read");n=raw[0];m=raw[1];rp=raw.data()+2;col=rp+n+1;if(raw.size()!=size_t(n)+m+3)throw std::runtime_error("shape");}
};
template<class T> void array_json(const std::vector<T>&v){std::cout<<"[";for(size_t i=0;i<v.size();i++){if(i)std::cout<<",";std::cout<<"[";for(size_t k=0;k<v[i].size();k++){if(k)std::cout<<",";std::cout<<v[i][k];}std::cout<<"]";}std::cout<<"]";}
'''
(C/'common.hpp').write_text(header)
s=(P/'code/trust/trust_gap_kernel.cpp').read_text().replace('#include "api/dataflow/dataflow_api.h"','').replace('const uint32_t id=cid*ENGINES+ENGINE,workers=nc*ENGINES;','const uint32_t id=cpu_engine,workers=cpu_engines;')
s=s.replace('const uint32_t base=', 'const uintptr_t base=').replace('const uint32_t row_base=', 'const uintptr_t row_base=').replace('(uint32_t)', '(uintptr_t)')
acc=r'''
auto transfer=[&](uint32_t which,uint64_t lo,uint64_t hi,uintptr_t dst){auto a=which?graph->col:graph->rp;uint64_t size=which?graph->m:graph->n+1;auto d=(uint32_t*)dst;for(uint64_t i=lo;i<hi;i++){d[i-lo]=i<size?a[i]:0;}};
auto read_row_page=[&](uint32_t pg,uintptr_t dst){transfer(0,uint64_t(pg)*PAGE_WORDS,uint64_t(pg+1)*PAGE_WORDS,dst);};
auto read_col_page=[&](uint32_t pg,uintptr_t dst){transfer(1,uint64_t(pg)*PAGE_WORDS,uint64_t(pg+1)*PAGE_WORDS,dst);};
auto range=[&](uint32_t which,uint64_t lo,uint64_t hi,uintptr_t dst){uint64_t first=lo&~uint64_t(15),last=(hi+15)&~uint64_t(15);transfer(which,first,last,dst);if(last>first){io_requests[which]+=(last-1)/PAGE_WORDS-first/PAGE_WORDS+1;io_bytes[which]+=(last-first)*4;}};
auto read_row_range=[&](uint64_t lo,uint64_t hi,uintptr_t dst){range(0,lo,hi,dst);};
auto read_col_range=[&](uint64_t lo,uint64_t hi,uintptr_t dst){range(1,lo,hi,dst);};
const int output=0;
'''
s=s.replace('// GENERATED_ACCESSORS',acc)
pre=r'''
#include "common.hpp"
CSR*graph;uint32_t cpu_engine,cpu_engines;std::vector<uint32_t> scratch(512*1024),snapshot;
template<class T>T get_common_arg_val(uint32_t k){return T(k==3?1:k==4?cpu_engines:k==5||k==7?graph->n:k==8?1:0);}
uint32_t get_absolute_logical_x(){return 0;} uint32_t get_absolute_logical_y(){return 0;}
uintptr_t get_write_ptr(uint32_t){return (uintptr_t)scratch.data();}
void noc_async_read_barrier(){} void noc_async_write_barrier(){}
void noc_async_write_tile(uint32_t,int,uintptr_t p){snapshot.assign((uint32_t*)p,(uint32_t*)p+1024);}
'''
post=r'''
int main(int argc,char**argv){try{if(argc!=3)throw std::runtime_error("args");CSR g(argv[1]);graph=&g;cpu_engines=std::stoul(argv[2]);std::vector<std::array<U,8>> rows;
for(cpu_engine=0;cpu_engine<cpu_engines;cpu_engine++){kernel_main();if(snapshot[22])throw std::runtime_error("kernel_error_"+std::to_string(snapshot[22]));auto v=[](int k){return U(snapshot[k])+(U(snapshot[k+1])<<32);};rows.push_back({v(0),v(4),v(32)+v(6),v(34)+v(8),v(36)+v(6)*PAGE_BYTES,v(38)+v(8)*PAGE_BYTES,v(40),snapshot[23]});}
std::cout<<"{\"engine\":";array_json(rows);std::cout<<"}\n";return 0;}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
'''
(C/'trust_host.cpp').write_text(pre+s+post)
# Actual kernel's dynamic allocation policy is represented with a generous source cap for fixtures; page/cache counts unchanged.
records=[]
for level in range(5):
 direct=int(level>=3);oa=int(level>=2);pb=16384 if direct else 1024;rs=16384//pb;cs=65536//pb;cur=0;defs={}
 for name,size in [('BINS_OFF',0 if oa else 4096),('TABLE_OFF',0 if oa else 409600),('HASH_OFF',65536 if oa else 0),('USED_OFF',16384*4 if oa else 0),('SOURCE_OFF',(16384+32)*4),('TAGS_OFF',((rs+cs+31)//32*32)*4),('ROWC_OFF',81920),('STAGE_OFF',8192 if direct else 128),('ARENA_OFF',65536 if direct else 0),('RESULT_OFF',4096)]:defs[name]=cur;cur+=(size+63)//64*64
 defs.update(ENGINE=0,ENGINES=2,PROFILE=1,PAGE_BYTES=pb,PAGE_WORDS=pb//4,ROW_SLOTS=rs,COL_SLOTS=cs,BUCKET_CAP=100,SOURCE_CAP=16384,HASH_SIZE=16384,PRUNE=int(level>=1),HASH_OA=oa,HASH_MIX=2 if oa else 0,DIRECT=direct,LOOKUP_WIDTH=4 if level==4 else 1,META_STAGE=64,ARENA_WORDS=16384)
 cmd=['c++','-O2','-std=c++17',*[f'-D{k}={v}' for k,v in defs.items()],str(C/'trust_host.cpp'),'-o',str(O/f'L{level}')]
 r=subprocess.run(cmd,capture_output=True,text=True);(O/f'L{level}.stderr').write_text(r.stderr);records.append(dict(level=level,command=cmd,returncode=r.returncode));
 if r.returncode:break
(O/'BUILD.json').write_text(json.dumps(dict(records=records),indent=2)+'\n')
raise SystemExit(any(r['returncode'] for r in records))
