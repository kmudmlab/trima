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
