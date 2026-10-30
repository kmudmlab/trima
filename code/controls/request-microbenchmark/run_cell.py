#!/usr/bin/env python3
"""새 프로세스 하나의 NoC 조건. 상위 campaign의 동일 hardware.lock fd를 상속한다."""
import argparse,fcntl,hashlib,json,os,statistics,subprocess,time
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent;LOCK=P.parents[1]/'hardware.lock';CB=576*1024

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--cores',type=int,choices=[1,110],required=True)
 ap.add_argument('--engines',type=int,choices=[1,2],required=True);ap.add_argument('--size',type=int,default=64);ap.add_argument('--batch',type=int,default=1)
 ap.add_argument('--pattern',choices=['random','contiguous'],default='random');ap.add_argument('--seed',type=int,default=20261022)
 ap.add_argument('--fixture',action='store_true');ap.add_argument('--calibration',action='store_true');ap.add_argument('--lock-fd',type=int,required=True)
 a=ap.parse_args();assert a.size in [64,128,256,512,1024,2048,4096,8192,16384] and a.batch in [1,2,4,8,16,32]
 assert (a.cores,a.engines) in [(1,1),(110,2)]
 assert os.fstat(a.lock_fd).st_ino==LOCK.stat().st_ino;fcntl.flock(a.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 owner=subprocess.run(['fuser','/dev/tenstorrent/0'],capture_output=True,text=True);assert owner.returncode==1 and not owner.stdout.strip()
 a.out.mkdir(parents=True,exist_ok=False);total=a.cores*a.engines
 import torch,ttnn
 dev=ttnn.open_device(device_id=0)
 try:
  # CPU initialization is sequential under hardware.lock, before any device launch.
  data=np.arange(64*1024*1024//4,dtype=np.uint32)^np.uint32(0xa5a55a5a)
  host=ttnn.from_torch(torch.from_numpy(data.reshape(-1,4096).view(np.int32)),dtype=ttnn.uint32,layout=ttnn.ROW_MAJOR_LAYOUT)
  inp=ttnn.to_device(host,dev,memory_config=ttnn.DRAM_MEMORY_CONFIG)
  zeros=ttnn.from_torch(torch.zeros((221,16),dtype=torch.int32),dtype=ttnn.uint32,layout=ttnn.ROW_MAJOR_LAYOUT)
  ctrl=ttnn.to_device(zeros,dev,memory_config=ttnn.DRAM_MEMORY_CONFIG)
  out=ttnn.allocate_tensor_on_device(ttnn.Shape([220,1024]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
  ttnn.synchronize_device(dev);tensors=[inp,ctrl,out];assert all(t.buffer_address()%64==0 for t in tensors);gx=1 if a.cores==1 else 11;gy=1 if a.cores==1 else 10
  cr=ttnn.CoreRangeSet([ttnn.CoreRange(ttnn.CoreCoord(0,0),ttnn.CoreCoord(gx-1,gy-1))]);cta=[];setup=[]
  for j,(tensor,name,pb) in enumerate(zip(tensors,['input','control','output'],[16384,64,4096])):
   cta+=list(ttnn.TensorAccessorArgs(tensor).get_compile_time_args());offset='0' if j==0 else f'a{j-1}.next_compile_time_args_offset()'
   setup += [f'constexpr auto a{j}=TensorAccessorArgs<{offset}>();',f'const auto {name}=TensorAccessor(a{j},get_common_arg_val<uint32_t>({j}),{pb});']
  source=(P/'kernel.cpp').read_text().replace('// ACCESSORS','\n'.join(setup));codes=['#define ENGINE '+str(i)+'\n'+source for i in range(a.engines)]
  for i,code in enumerate(codes):(a.out/f'engine{i}.cpp').write_text(code)
  config={k:str(v) if isinstance(v,Path) else v for k,v in vars(a).items()};config.update(cb_bytes_per_dm=CB,actual_cb_descriptor_bytes_per_core=CB*a.engines,input_page_bytes=16384,pool_bytes=data.nbytes,timestamp_unit='SDK wall-clock ticks; seconds only via block calibration')
  (a.out/'config.json').write_text(json.dumps(config,indent=2)+'\n');rows=[];epoch=0
  levels=[1000000,10000000,100000000] if a.calibration else [64] if a.fixture else [0,1024,4096]
  for level in levels:
   for rep in range(4):
    epoch+=1;n=0 if a.calibration else level;spin=level if a.calibration else 0
    common=[t.buffer_address() for t in tensors]+[gx,a.engines,total,n,a.size,a.batch,int(a.pattern=='random'),a.seed,epoch,int(a.fixture),spin]
    kernels=[ttnn.KernelDescriptor(kernel_source=code,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cr,compile_time_args=cta,common_runtime_args=common,runtime_args=[],config=ttnn.ReaderConfigDescriptor() if i==0 else ttnn.WriterConfigDescriptor()) for i,code in enumerate(codes)]
    cbs=[ttnn.CBDescriptor(total_size=CB,core_ranges=cr,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=i,data_format=ttnn.uint32,page_size=4096)]) for i in range(a.engines)]
    program=ttnn.ProgramDescriptor(kernels=kernels,cbs=cbs,semaphores=[])
    started=time.perf_counter();ttnn.generic_op(tensors,program);ttnn.synchronize_device(dev);host_s=time.perf_counter()-started
    raw=ttnn.to_torch(out).numpy().astype(np.uint32)[:total];np.save(a.out/f'raw-{level}-{rep}.npy',raw)
    assert np.all(raw[:,0]==0x4e4f4331) and np.array_equal(raw[:,1],np.arange(total)) and np.all(raw[:,2]==0),'device data/gate failure'
    for col,value in [(3,n),(4,a.size),(5,a.batch),(6,total),(7,int(a.pattern=='random')),(10,epoch),(11,(n+a.batch-1)//a.batch),(12,int(a.fixture)),(13,spin)]:assert np.all(raw[:,col]==value),(col,value)
    ticks=raw[:,8].astype(np.uint64)+(raw[:,9].astype(np.uint64)<<32);assert np.all(ticks>0)
    r=dict(level=level,n_per_dm=n,spin_ticks=spin,warmup=rep==0,rep=rep,host_seconds=host_s,dm_max_ticks=int(ticks.max()),dm_ticks_min=int(ticks.min()),dm_ticks_p50=float(np.median(ticks)),dm_ticks_p95=float(np.quantile(ticks,.95)),requests=total*n,bytes=total*n*a.size,barriers=total*((n+a.batch-1)//a.batch))
    starts=raw[:,14].astype(np.uint64)+(raw[:,15].astype(np.uint64)<<32);stops=raw[:,16].astype(np.uint64)+(raw[:,17].astype(np.uint64)<<32)
    r.update(start_spread_ticks=int(starts.max())-int(starts.min()),all_dm_overlap_ticks=max(0,int(stops.min())-int(starts.max())),global_span_ticks=int(stops.max())-int(starts.min()))
    rows.append(r)
    with (a.out/'samples.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
    if total>1 and n and not a.fixture:assert r['all_dm_overlap_ticks']>0, 'No interval with all 220 DM active; preserve cell and stop'
  summary=dict(status='pass',config=config,rows=rows,levels={str(level):dict(dm_max_ticks=statistics.median(r['dm_max_ticks'] for r in rows if r['level']==level and not r['warmup']),host_seconds=statistics.median(r['host_seconds'] for r in rows if r['level']==level and not r['warmup'])) for level in levels})
  (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 finally:ttnn.close_device(dev)
if __name__=='__main__':main()
