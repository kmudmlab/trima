"""Mac CPU: 전수 주소 규칙, 식별성, 실제 kernel의 async memcpy/220-thread fixture."""
import hashlib,json,subprocess,tempfile
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent;records=[]
def mix(x):
 x=x.astype(np.uint32);x^=x>>16;x*=np.uint32(0x7feb352d);x^=x>>15;x*=np.uint32(0x846ca68b);return x^(x>>16)
ids=np.arange(220,dtype=np.uint32)[:,None];k=np.arange(4096,dtype=np.uint32)[None,:]
for seed in [20261022,20261023,20261024]:
 h=mix(k^mix(ids+seed))
 for size in [64,128,256,512,1024,2048,4096,8192,16384]:
  offsets=[(h%4096)*16384+(mix(h^np.uint32(0x9e3779b9))%((16384-size)//64+1))*64,(ids*65536+k*size)%(64*1024*1024)]
  for off in offsets:assert np.all(off%64==0) and np.all(off+size<=64*1024*1024) and np.all(off%16384+size<=16384)
  for batch in [1,2,4,8,16,32]:assert batch*size<=512*1024 and 4096%batch==1024%batch==64%batch==0
records.append(dict(case='all_220_DM_4096_addresses_9_sizes_3_seeds_2_patterns',status='pass'))
X=np.array([[1,220*n,220*n*s,220*n/b] for n in [0,1024,4096] for s in [64,128,256,512,1024,2048,4096,8192,16384] for b in [1,2,4,8,16,32]],dtype=float);assert np.linalg.matrix_rank(X)==4
records.append(dict(case='cost_model_rank_4',status='pass'))
with tempfile.TemporaryDirectory() as tmp:
 t=Path(tmp);(t/'api/dataflow').mkdir(parents=True);(t/'api/dataflow/dataflow_api.h').write_text('#pragma once\n')
 src=(P/'kernel.cpp').read_text().replace('// ACCESSORS','const Accessor input{pool.data(),16384},control{control_words.data(),64},output{output_words.data(),4096};')
 code='#include "mock_device.hpp"\n#include <iostream>\nnamespace dm0 {\n#define ENGINE 0\n'+src+'\n#undef ENGINE\n}\nnamespace dm1 {\n#define ENGINE 1\n'+src+'\n#undef ENGINE\n}\n'
 code+='''
int main() {
 pool.resize(64*1024*1024/4);for(uint32_t i=0;i<pool.size();i++) { pool[i]=i^0xa5a55a5au; }
 control_words.resize(221*16);output_words.resize(220*1024);
 for(uint32_t fixture=0;fixture<3;fixture++) {
  uint32_t total=fixture?220:1,size=fixture?16384:64,batch=fixture?32:1;
  std::fill(control_words.begin(),control_words.end(),0);
  std::vector<std::thread> workers;
  for(uint32_t id=0;id<total;id++) {
   workers.emplace_back([=]() {
    scratch.resize(576*1024/4);engine_id=id;
    args={0,0,0,fixture?11u:1u,fixture?2u:1u,total,64,size,batch,fixture==2?0u:1u,20261022,1,1,0};
    if(fixture && id%2) { dm1::kernel_main(); } else { dm0::kernel_main(); }
   });
  }
  for(auto& thread:workers) { thread.join(); }
  for(uint32_t id=0;id<total;id++) {
   auto o=output_words.data()+id*1024;
   if(o[0]!=0x4e4f4331u || o[1]!=id || o[2] || o[3]!=64 || o[11]!=64/batch) { std::cerr<<"fixture failure "<<fixture<<" "<<id<<" "<<o[2]<<"\\n";return 1; }
  }
  std::cout<<"fixture "<<fixture<<" passed "<<total<<" DM\\n";
 }
}
'''
 (t/'mock.cpp').write_text(code)
 subprocess.run(['clang++','-O2','-std=c++17','-Wall','-Wextra','-Werror','-pthread','-I'+str(t),'-I'+str(P),str(t/'mock.cpp'),'-o',str(t/'mock')],check=True)
 result=subprocess.check_output([str(t/'mock')],text=True);print(result,end='');records.append(dict(case='actual_kernel_3_fixtures_async_mock_all_words',status='pass',stdout=result))
out=dict(status='pass',checks=records,source_sha256={name:hashlib.sha256((P/name).read_bytes()).hexdigest() for name in ['kernel.cpp','mock_device.hpp','test_cpu.py']},device_compilation='not_run; CPU mock does not validate TT SDK integration')
(P/'cpu-validation.json').write_text(json.dumps(out,indent=2)+'\n');print('CPU checks passed')
