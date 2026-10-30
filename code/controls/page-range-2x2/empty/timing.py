"""검증 전용 empty-work Count 경계. 시간 측정 진입점은 등록 후 별도로 승인한다."""
from pathlib import Path
import argparse,fcntl,json,hashlib,traceback,time,statistics
import numpy as np
from device_wait import wait_device_free
R=Path(__file__).resolve().parent

def main():
 a=argparse.ArgumentParser();a.add_argument('--path',choices=['B','L7'],required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
 args.out.mkdir(parents=True,exist_ok=False)
 layout=json.loads((R/'LAYOUT.json').read_bytes())[args.path];sizes=layout['descriptor_bytes'];owners=layout['output_owners']
 assert sum(sizes)==layout['total_cb_bytes']<=1392*1024
 lock=(R.parents[3]/'hardware.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 wait_device_free(args.out/'device-wait.json','before_open_device')
 import torch,ttnn
 from scan_b import reduce_counts as reduce_b
 from scan_l7 import reduce_counts as reduce_l7
 reduce_counts=reduce_b if args.path=='B' else reduce_l7
 dev=ttnn.open_device(device_id=0)
 try:
  cores=ttnn.CoreRangeSet([ttnn.CoreRange(ttnn.CoreCoord(0,0),ttnn.CoreCoord(10,9))])
  cbs=[ttnn.CBDescriptor(total_size=z,core_ranges=cores,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=i,data_format=ttnn.uint32,page_size=4096)]) for i,z in enumerate(sizes)]
  def upload(x):return ttnn.to_device(ttnn.from_torch(torch.from_numpy(x),dtype=ttnn.uint32,layout=ttnn.ROW_MAJOR_LAYOUT),dev,memory_config=ttnn.DRAM_MEMORY_CONFIG)
  # CSR 없음. generic_opの2入力以上契約用の未読テンソル。Countの入力転送は0。
  dummy=upload(np.zeros((1,4096),np.int32))
  output=ttnn.allocate_tensor_on_device(ttnn.Shape([owners,1024]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
  ct=list(ttnn.TensorAccessorArgs(output).get_compile_time_args());common=[0,0,output.buffer_address(),11]
  def kd(code,cfg,cta=ct):return ttnn.KernelDescriptor(kernel_source=code,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cores,compile_time_args=cta,common_runtime_args=common,runtime_args=[],config=cfg)
  discover='#include "api/dataflow/dataflow_api.h"\nvoid kernel_main(){constexpr auto a=TensorAccessorArgs<0>();auto o=TensorAccessor(a,get_common_arg_val<uint32_t>(2),4096);uint32_t p=get_write_ptr(0);'+''.join(f'((uint32_t*)p)[{i}]=get_write_ptr({i});' for i in range(len(sizes)))+'uint32_t id=get_absolute_logical_y()*11+get_absolute_logical_x();noc_async_write_tile(id,o,p);noc_async_write_barrier();}'
  ttnn.generic_op([dummy,output],ttnn.ProgramDescriptor(kernels=[kd(discover,ttnn.ReaderConfigDescriptor())],cbs=cbs,semaphores=[]));ttnn.synchronize_device(dev)
  addresses=ttnn.to_torch(output).numpy()[:110,:len(sizes)];assert np.all(addresses==addresses[0])
  (args.out/'cb-allocation.json').write_text(json.dumps(dict(descriptor_bytes=sizes,total_cb_bytes=sum(sizes),cb_addresses=addresses.tolist(),limit_bytes=1392*1024),indent=2)+'\n')
  kernels=[]
  for engine in range(2):
   emit=args.path=='B' or engine==0
   owner=f'core*2+{engine}' if args.path=='B' else 'core'
   zero_words=1024 if args.path=='B' else 25
   extra_zero='' if args.path=='B' else 'for(uint32_t i=26;i<36;i++){((uint32_t*)p)[i]=0;}'
   code='#include "api/dataflow/dataflow_api.h"\nvoid kernel_main(){'
   if emit:code+=f'constexpr auto a=TensorAccessorArgs<0>();auto o=TensorAccessor(a,get_common_arg_val<uint32_t>(2),4096);uint32_t p=get_write_ptr({engine});uint32_t core=get_absolute_logical_y()*11+get_absolute_logical_x();for(uint32_t i=0;i<{zero_words};i++){{((uint32_t*)p)[i]=0;}}{extra_zero}((uint32_t*)p)[24]={owner};noc_async_write_tile({owner},o,p);noc_async_write_barrier();'
   code+='}'
   (args.out/f'dm{engine}.cpp').write_text(code);kernels.append(kd(code,ttnn.ReaderConfigDescriptor() if engine==0 else ttnn.WriterConfigDescriptor()))
  if args.path=='L7':
   code='#include "api/compute/compute_kernel_api.h"\n#include "api/compute/common.h"\nvoid kernel_main(){}\n'
   cfg=ttnn.ComputeConfigDescriptor();cfg.fp32_dest_acc_en=True;cfg.dst_full_sync_en=False;cfg.unpack_to_dest_mode=[ttnn.UnpackToDestMode.UnpackToDestFp32]*64
   kernels.append(kd(code,cfg,[]));(args.out/'compute.cpp').write_text(code)
  program=ttnn.ProgramDescriptor(kernels=kernels,cbs=cbs,semaphores=[])
  poison='#include "api/dataflow/dataflow_api.h"\nvoid kernel_main(){constexpr auto a=TensorAccessorArgs<0>();auto o=TensorAccessor(a,get_common_arg_val<uint32_t>(2),4096);uint32_t p=get_write_ptr(0);for(uint32_t i=0;i<1024;i++){((uint32_t*)p)[i]=0xdeadbeef;}uint32_t id=get_absolute_logical_y()*11+get_absolute_logical_x();'+('noc_async_write_tile(id*2,o,p);noc_async_write_tile(id*2+1,o,p);' if args.path=='B' else 'noc_async_write_tile(id,o,p);')+'noc_async_write_barrier();}'
  poison_program=ttnn.ProgramDescriptor(kernels=[kd(poison,ttnn.ReaderConfigDescriptor())],cbs=cbs,semaphores=[])
  elapsed=[]
  for rep in range(4):
   ttnn.generic_op([dummy,output],poison_program);ttnn.synchronize_device(dev)
   start=time.perf_counter()
   # Count 경계: launch + synchronize + 既存reduce_counts(小readback含む)。検証では時計を読まない。
   ttnn.generic_op([dummy,output],program);ttnn.synchronize_device(dev)
   total,err=reduce_counts(ttnn,dev,ttnn.CoreCoord(owners,1),output)
   duration=time.perf_counter()-start
   if rep>0:elapsed.append(duration)
   raw=ttnn.to_torch(output).numpy().astype(np.uint32);expected=np.zeros((owners,1024),np.uint32);expected[:,24]=np.arange(owners)
   fields=list(range(1024)) if args.path=='B' else list(range(25))+list(range(26,36))
   assert total==0 and err==0 and np.array_equal(raw[:,fields],expected[:,fields]),'empty output/count mismatch'
   np.save(args.out/f'result-{rep}.npy',raw)
  (args.out/'summary.json').write_text(json.dumps(dict(status='pass',path=args.path,launches=4,warmup_runs=1,measured_runs=3,samples_s=elapsed,median_s=statistics.median(elapsed),upload_excluded=True,counters=0,zero_count_exact=True,per_owner_exact=True,timing_measured=True,CB_bytes=sum(sizes)),indent=2)+'\n')
 finally:ttnn.close_device(dev);lock.close()
if __name__=='__main__':
 try:main()
 except BaseException:
  import sys
  d=Path(sys.argv[sys.argv.index('--out')+1]);d.mkdir(parents=True,exist_ok=True);(d/'failure.json').write_text(json.dumps(dict(traceback=traceback.format_exc()),indent=2)+'\n');raise
