import time
from pathlib import Path
import numpy as np

def device_scan(ttnn,dev,core_set,grid,lengths,hptr,totals,n,pb,chunk_words,out,log):
 pw=pb//4;cp=chunk_words//pw;nc=grid.x*grid.y
 tensors=lengths+hptr+[totals];cta=[];access=[]
 for j,t in enumerate(tensors):
  cta+=list(ttnn.TensorAccessorArgs(t).get_compile_time_args());off='0' if j==0 else f'a{j-1}.next_compile_time_args_offset()'
  access+=[f'constexpr auto a{j}=TensorAccessorArgs<{off}>();',f'const auto t{j}=TensorAccessor(a{j},get_common_arg_val<uint32_t>({3+j}),{pb});']
 for name,ids in [('length',range(len(lengths))),('hptr',range(len(lengths),len(lengths)+len(hptr)))]:
  access.append(f'auto addr_{name}=[&](uint32_t pg)->uint64_t{{switch(pg/{cp}u){{')
  for k,j in enumerate(ids):access.append(f'case {k}:return get_noc_addr(pg%{cp}u,t{j});')
  access.append('}return 0;};')
 access.append(f'uint64_t summary=get_noc_addr(0,t{len(tensors)-1});')
 source='''#include <stdint.h>
#include "api/dataflow/dataflow_api.h"
void kernel_main(){
 const uint32_t n=get_common_arg_val<uint32_t>(0),gx=get_common_arg_val<uint32_t>(1),nc=get_common_arg_val<uint32_t>(2);
 const uint32_t id=get_absolute_logical_y()*gx+get_absolute_logical_x();
 // ACCESS
 auto p=(uint32_t*)get_write_ptr(0);auto q=(uint64_t*)(p+PW);
 const uint32_t pages=(n+1+PW-1)/PW,block=(pages+nc-1)/nc,begin=id*block,stop=(begin+block<pages?begin+block:pages);
#if PHASE == 0
 uint64_t sum=0;uint32_t maximum=0;
 for(uint32_t pg=begin;pg<stop;pg++){
  noc_async_read(addr_length(pg),(uint32_t)p,PB);noc_async_read_barrier();
  for(uint32_t j=0;j<PW;j++){q[j]=sum;if(uint64_t(pg)*PW+j<n){sum+=p[j];if(p[j]>maximum)maximum=p[j];}}
  noc_async_write((uint32_t)q,addr_hptr(pg*2),PB);noc_async_write((uint32_t)(q+PW/2),addr_hptr(pg*2+1),PB);noc_async_write_barrier();
 }
 p[0]=sum;p[1]=sum>>32;p[2]=maximum;p[3]=0;
 noc_async_write((uint32_t)p,summary+id*16,16);noc_async_write_barrier();
#else
 noc_async_read(summary,(uint32_t)p,PB);noc_async_read_barrier();uint64_t offset=0,total=0;uint32_t maximum=0;
 for(uint32_t i=0;i<nc;i++){uint64_t s=uint64_t(p[i*4])+(uint64_t(p[i*4+1])<<32);if(i<id)offset+=s;total+=s;if(p[i*4+2]>maximum)maximum=p[i*4+2];}
 for(uint32_t pg=begin*2;pg<stop*2;pg++){
  noc_async_read(addr_hptr(pg),(uint32_t)q,PB);noc_async_read_barrier();for(uint32_t j=0;j<PW/2;j++)q[j]+=offset;
  noc_async_write((uint32_t)q,addr_hptr(pg),PB);noc_async_write_barrier();
 }
 if(id==0){p[0]=total;p[1]=total>>32;p[2]=maximum;p[3]=0;noc_async_write((uint32_t)p,summary+nc*16,16);noc_async_write_barrier();}
#endif
}
'''.replace('// ACCESS','\n'.join(access))
 cb=ttnn.CBDescriptor(total_size=3*pb,core_ranges=core_set,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=0,data_format=ttnn.uint32,page_size=pb)])
 t=time.perf_counter()
 for phase in [0,1]:
  body=f'#define PHASE {phase}\n#define PW {pw}\n#define PB {pb}\n'+source
  (out/f'scan-{phase}.cpp').write_text(body)
  kd=ttnn.KernelDescriptor(kernel_source=body,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=core_set,compile_time_args=cta,common_runtime_args=[n,grid.x,nc]+[x.buffer_address() for x in tensors],runtime_args=[],config=ttnn.ReaderConfigDescriptor())
  ttnn.generic_op(tensors,ttnn.ProgramDescriptor(kernels=[kd],semaphores=[],cbs=[cb]));ttnn.synchronize_device(dev)
 a=ttnn.to_torch(totals).numpy().ravel();words=int(a[nc*4])+(int(a[nc*4+1])<<32);maximum=int(a[nc*4+2]);elapsed=time.perf_counter()-t
 log(kind='device_scan',seconds=elapsed,hash_words=words,max_record=maximum)
 return words,max(32,(maximum+16+31)//32*32)

def reduce_counts(ttnn,dev,grid,output):
 cores=ttnn.CoreRangeSet([ttnn.CoreRange(ttnn.CoreCoord(0,0),ttnn.CoreCoord(0,0))])
 result=ttnn.allocate_tensor_on_device(ttnn.Shape([1,1024]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
 a=list(ttnn.TensorAccessorArgs(output).get_compile_time_args());a+=list(ttnn.TensorAccessorArgs(result).get_compile_time_args())
 body='''#include <stdint.h>
#include "api/dataflow/dataflow_api.h"
void kernel_main(){constexpr auto a=TensorAccessorArgs<0>();constexpr auto b=TensorAccessorArgs<a.next_compile_time_args_offset()>();auto src=TensorAccessor(a,get_common_arg_val<uint32_t>(0),4096);auto dst=TensorAccessor(b,get_common_arg_val<uint32_t>(1),4096);auto p=(uint32_t*)get_write_ptr(0);uint64_t count=0,sources=0;uint32_t err=0;
for(uint32_t i=0;i<get_common_arg_val<uint32_t>(2);i++){noc_async_read_tile(i,src,(uint32_t)p);noc_async_read_barrier();count+=uint64_t(p[0])+(uint64_t(p[1])<<32);sources+=uint64_t(p[2])+(uint64_t(p[3])<<32);err|=p[22];}
p[0]=count;p[1]=count>>32;p[2]=sources;p[3]=sources>>32;p[4]=err;noc_async_write_tile(0,dst,(uint32_t)p);noc_async_write_barrier();}
'''
 kd=ttnn.KernelDescriptor(kernel_source=body,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cores,compile_time_args=a,common_runtime_args=[output.buffer_address(),result.buffer_address(),grid.x*grid.y],runtime_args=[],config=ttnn.ReaderConfigDescriptor())
 cb=ttnn.CBDescriptor(total_size=4096,core_ranges=cores,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=0,data_format=ttnn.uint32,page_size=4096)])
 ttnn.generic_op([output,result],ttnn.ProgramDescriptor(kernels=[kd],semaphores=[],cbs=[cb]));ttnn.synchronize_device(dev)
 v=ttnn.to_torch(result).numpy().ravel();count=int(v[0])+(int(v[1])<<32);err=int(v[4]);ttnn.deallocate(result);return count,err
