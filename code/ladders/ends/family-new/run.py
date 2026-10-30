"""Task28 family correctness only. No clock API and no endpoint-pair input."""
import statistics,time,argparse,fcntl,hashlib,json,os,re,subprocess,traceback
from pathlib import Path
import numpy as np
from device_wait import wait_device_free
from reduce import reduce_counts
HERE=Path(__file__).resolve().parent;P=HERE.parent;G=P.parent
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(16<<20),b''):h.update(b)
 return h.hexdigest()
def write(path,data):path.write_text(json.dumps(data,indent=2)+'\n')

def accessors(ttnn,tensors,groups,pbs,chunk_words,pb,row_pb=16384):
 cta=[];code=[]
 for j,t in enumerate(tensors):
  cta+=list(ttnn.TensorAccessorArgs(t).get_compile_time_args())
  prev='0' if j==0 else f'a{j-1}.next_compile_time_args_offset()'
  code += [f'constexpr auto a{j}=TensorAccessorArgs<{prev}>();',
           f'const auto t{j}=TensorAccessor(a{j},get_common_arg_val<uint32_t>({7+j}),{pbs[j]});']
 code.append(f'const auto output=t{len(tensors)-1};')
 code.append('auto word_addr=[&](uint32_t which,uint64_t p)->uint64_t { switch(which){')
 for which,group in enumerate(groups):
  size=row_pb if which==0 else pb;pw=size//4;cp=chunk_words//pw
  code.append(f'case {which}: {{ uint32_t pg=p/{pw}u,off=p%{pw}u; switch(pg/{cp}u){{')
  for c,j in enumerate(group):code.append(f'case {c}:return get_noc_addr(pg%{cp}u,t{j})+off*4;')
  code.append('} break; }')
 code.append('} return 0; };')
 code.append('auto read_page=[&](uint32_t which,uint32_t pg,uint32_t dst){noc_async_read(word_addr(which,uint64_t(pg)*PAGE_WORDS),dst,PAGE_BYTES);};')
 code.append('auto range_read=[&](uint32_t which,uint64_t lo,uint64_t hi,uint32_t dst){uint64_t p=lo&~uint64_t(15),stop=(hi+15)&~uint64_t(15);while(p<stop){uint32_t words=PAGE_WORDS-p%PAGE_WORDS;if(words>stop-p){words=stop-p;}noc_async_read(word_addr(which,p),dst,words*4);p+=words;dst+=words*4;}};')
 if row_pb==16384:code.append('auto row_range_16k=[&](uint32_t lo,uint32_t hi,uint32_t dst){uint64_t p=lo&~uint64_t(15),stop=(uint64_t(hi)+15)&~uint64_t(15);while(p<stop){uint32_t words=4096-p%4096;if(words>stop-p){words=stop-p;}noc_async_read(word_addr(0,p),dst,words*4);p+=words;dst+=words*4;}};')
 return cta,'\n'.join(code)

def main():
 ap=argparse.ArgumentParser()
 for key in ['input','schedule','replay','out']:ap.add_argument('--'+key,type=Path,required=True)
 ap.add_argument('--reference',type=Path);ap.add_argument('--input-sha',required=True);ap.add_argument('--schedule-sha',required=True)
 ap.add_argument('--family',choices=['steptc','wetric','tricore'],required=True)
 ap.add_argument('--supply',choices=['cache','range'],required=True);ap.add_argument('--expected',type=int,required=True)
 ap.add_argument('--legacy-anchor',action='store_true')
 ap.add_argument('--tail',type=int,choices=[0,1],required=True);ap.add_argument('--trisc',type=int,choices=[0,1],required=True);ap.add_argument('--contexts',type=int,choices=[1,2],required=True)
 ap.add_argument('--validate-only',action='store_true');ap.add_argument('--reps',type=int,default=3)
 args=ap.parse_args();assert args.reps==3;args.out.mkdir(parents=True,exist_ok=False)
 assert not args.legacy_anchor and (args.contexts==1 or (args.family=='steptc' and args.tail==1 and args.trisc==1))
 if args.legacy_anchor:assert args.family=='steptc' and args.supply=='range'
 source_dir=P/'anchor-trisc' if args.legacy_anchor else HERE
 row_pb=1024 if args.legacy_anchor else 16384
 lock=(Path(__file__).resolve().parents[4]/'hardware.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 wait_device_free(args.out/'device-wait-host.json','before_host_preparation')
 assert sha(args.input)==args.input_sha and sha(args.schedule)==args.schedule_sha,'input/schedule SHA'
 cpu=json.loads(args.replay.read_text());assert len(cpu['engines'])==220
 raw=np.memmap(args.input,dtype='<u4',mode='r');n,m=map(int,raw[:2]);assert len(raw)==n+m+3
 schedule=np.memmap(args.schedule,dtype='<u4',mode='r')
 arrays=[raw[2:n+3],raw[n+3:],schedule]
 pb=1024 if args.family=='steptc' else 256;chunk_words=256*1024*1024//4
 tail_first=(n-min(n,65536))//16*16
 tail_bytes=((((n+16)//16*16-tail_first)*4+64+4095)//4096)*4096
 sizes=[344064,344064] if args.legacy_anchor else [495616 if args.contexts==2 else 409600]*2+[tail_bytes]
 assert sum(sizes)<=1392*1024
 config=dict(family=args.family,supply=args.supply,input_sha256=args.input_sha,schedule_sha256=args.schedule_sha,
             endpoint_array=False,source_cap=2240,hash_mix=(0 if args.legacy_anchor else 2) if args.family=='steptc' else None,
             source_contexts=args.contexts,tail_on=args.tail,trisc_on=args.trisc,batch=64,arena_words=16384,tail_vertices=65536 if args.tail else 0,merge_gap_units=None if args.legacy_anchor else 13,
             CSR_row_tensor_page_bytes=row_pb,logical_cache_page_bytes=pb,column_schedule_page_bytes=pb,
             legacy_anchor=args.legacy_anchor,
             descriptor_bytes=sizes,total_cb_bytes=sum(sizes),counters=0,timing_measured=not args.validate_only,
             n=n,m=m,expected_count=args.expected,replay_sha256=sha(args.replay))
 write(args.out/'config.json',config)
 import torch,ttnn
 wait_device_free(args.out/'device-wait-open.json','before_open_device')
 dev=ttnn.open_device(device_id=0)
 try:
  gx=11;cr=ttnn.CoreRangeSet([ttnn.CoreRange(ttnn.CoreCoord(0,0),ttnn.CoreCoord(10,9))])
  buffers=[];groups=[];pbs=[]
  for which,data in enumerate(arrays):
   group=[];size=row_pb if which==0 else pb;pw=size//4
   for offset in range(0,max(1,len(data)),chunk_words):
    part=data[offset:offset+chunk_words];padded=np.zeros((max(1,(len(part)+pw-1)//pw),pw),dtype=np.uint32);padded.ravel()[:len(part)]=part
    host=ttnn.from_torch(torch.from_numpy(padded.view(np.int32)),dtype=ttnn.uint32,layout=ttnn.ROW_MAJOR_LAYOUT)
    tensor=ttnn.to_device(host,dev,memory_config=ttnn.DRAM_MEMORY_CONFIG);ttnn.synchronize_device(dev)
    group.append(len(buffers));buffers.append(tensor);pbs.append(size);del host,padded
   groups.append(group)
  output=ttnn.allocate_tensor_on_device(ttnn.Shape([220,1024]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
  tensors=buffers+[output];pbs.append(4096)
  common=[gx,110,n,m,1,0,0]+[t.buffer_address() for t in tensors]
  cbs=[ttnn.CBDescriptor(total_size=size,core_ranges=cr,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=i,data_format=ttnn.uint32,page_size=4096)]) for i,size in enumerate(sizes)]
  discovery='''#include "api/dataflow/dataflow_api.h"
void kernel_main(){
 constexpr auto a=TensorAccessorArgs<0>();auto out=TensorAccessor(a,get_common_arg_val<uint32_t>(0),4096);
 auto p=(uint32_t*)get_write_ptr(0);
 for(uint32_t i=0;i<3;i++) {
  auto& cb=get_local_cb_interface(i);p[i*4]=get_write_ptr(i);p[i*4+1]=cb.fifo_size<<cb_addr_shift;
  p[i*4+2]=cb.fifo_limit<<cb_addr_shift;p[i*4+3]=cb_addr_shift;
  if(i<2) {
   auto sy=(volatile uint32_t*)(get_write_ptr(i)+4096);
   for(uint32_t j=0;j<1024;++j) { sy[j]=0; }
  }
 }
 ((volatile uint32_t*)get_write_ptr(2))[0]=0;
 uint32_t id=get_absolute_logical_y()*11+get_absolute_logical_x();
 noc_async_write_tile(id,out,(uint32_t)p);noc_async_write_barrier();
}'''
  if args.legacy_anchor:discovery=discovery.replace('i<3','i<2').replace(' ((volatile uint32_t*)get_write_ptr(2))[0]=0;','')
  kd=ttnn.KernelDescriptor(kernel_source=discovery,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cr,compile_time_args=list(ttnn.TensorAccessorArgs(output).get_compile_time_args()),common_runtime_args=[output.buffer_address()],runtime_args=[],config=ttnn.ReaderConfigDescriptor())
  ttnn.generic_op(tensors,ttnn.ProgramDescriptor(kernels=[kd],cbs=cbs,semaphores=[]));ttnn.synchronize_device(dev)
  addresses=ttnn.to_torch(output).numpy()[:110,:len(sizes)*4].astype(np.uint32)
  assert np.all(addresses==addresses[0])
  for i,size in enumerate(sizes):
   assert np.all(addresses[:,i*4+1]==size) and np.all(addresses[:,i*4+2]-addresses[:,i*4]==size)
   for j in range(i):assert int(addresses[0,i*4])>=int(addresses[0,j*4+2]) or int(addresses[0,j*4])>=int(addresses[0,i*4+2])
  common[5],common[6]=map(int,addresses[0,[0,4]])
  write(args.out/'cb-allocation.json',dict(total_cb_bytes=sum(sizes),descriptor_bytes=sizes,addresses=addresses.tolist(),limit_bytes=1392*1024))
  cta,setup=accessors(ttnn,tensors,groups,pbs,chunk_words,pb,row_pb)
  shared=(source_dir/'step_shared.hpp').read_text();metadata=(HERE/'metadata.hpp').read_text()
  prefix=f'#define PAGE_BYTES {pb}\n#define PAGE_WORDS {pb//4}\n#define FAMILY {dict(steptc=1,wetric=2,tricore=3)[args.family]}\n#define COUNTERS 0\n#define TRISC_ON {args.trisc}\n#define TAIL_ON {args.tail}\n#define SOURCE_CONTEXTS {args.contexts}\n#define DIRECT {int(args.supply=="range")}\n#define STRESS 0\n'
  reader=(source_dir/'step_reader.cpp').read_text().replace('// SHARED',shared).replace('// METADATA_PLAN',metadata).replace('// ACCESSORS',setup).replace('get_timestamp()','uint64_t(0)')
  worker=(source_dir/'step_worker.cpp').read_text().replace('// SHARED',shared).replace('get_timestamp()','uint64_t(0)')
  cfg=ttnn.ComputeConfigDescriptor();cfg.fp32_dest_acc_en=True;cfg.dst_full_sync_en=False;cfg.unpack_to_dest_mode=[ttnn.UnpackToDestMode.UnpackToDestFp32]*64
  kernels=[]
  for name,body,configuration,ct in [('reader','#define CHANNEL 0\n'+reader,ttnn.ReaderConfigDescriptor(),cta),('writer','#define CHANNEL 1\n'+reader,ttnn.WriterConfigDescriptor(),cta),('worker',worker,cfg,[])]:
   code=prefix+body;assert 'get_timestamp()' not in code
   (args.out/f'{name}.cpp').write_text(code)
   kernels.append(ttnn.KernelDescriptor(kernel_source=code,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cr,compile_time_args=ct,common_runtime_args=common,runtime_args=[],config=configuration))
  write(args.out/'manifest.json',{str(p):sha(p) for p in [Path(__file__),source_dir/'step_reader.cpp',source_dir/'step_worker.cpp',source_dir/'step_shared.hpp',HERE/'metadata.hpp',*args.out.glob('*.cpp')]})
  times=[]
  reference=np.load(args.reference) if args.reference else None
  for rep in range(1 if args.validate_only else 4):
   common[4]=rep+1
   for kernel in kernels:kernel.common_runtime_args=list(common)
   program=ttnn.ProgramDescriptor(kernels=kernels,cbs=cbs,semaphores=[])
   start=time.perf_counter() if not args.validate_only else None
   ttnn.generic_op(tensors,program);ttnn.synchronize_device(dev)
   count,error=reduce_counts(ttnn,dev,ttnn.CoreCoord(220,1),output)
   elapsed=time.perf_counter()-start if not args.validate_only else None
   a=ttnn.to_torch(output).numpy().astype(np.uint32);np.save(args.out/f'result-{rep}.npy',a)
   assert count==args.expected and error==0 and np.all(a[:,22]==0)
   assert np.array_equal(a[:,24],np.arange(220)) and np.all(a[:,25]==0x53545243)
   counts=[int(r[0])+(int(r[1])<<32) for r in a]
   assert sum(counts)==args.expected
   if reference is not None:assert np.array_equal(a[:,:2],reference[:,:2]),'frozen per-owner count'
   else:assert counts==[r[0] for r in cpu['engines']],'fixture per-owner count'
   if rep and not args.validate_only:times.append(elapsed)
  write(args.out/'summary.json',dict(status='pass',per_owner_exact=True,counters=0,
    warmup_runs=0 if args.validate_only else 1,measured_runs=len(times),samples_s=times,
    median_s=statistics.median(times) if times else None,timing_measured=not args.validate_only,
    upload_excluded=True,boundary='launch+synchronize+4KiB reducer readback',reducer_input_pages=220,
    cb_bytes=sum(sizes),endpoint_array=False))
 finally:ttnn.close_device(dev);lock.close()
if __name__=='__main__':
 try:main()
 except BaseException as exc:
  import sys
  out=Path(sys.argv[sys.argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True)
  message='\n'.join(line for line in str(exc).splitlines() if not re.search(r'(?i)(duration|elapsed|\b[0-9]+[.]?[0-9]*\s*(ms|seconds|secs)\b)',line))
  write(out/'failure.json',dict(error_type=type(exc).__name__,error=message,frames=[dict(file=f.filename,line=f.lineno,function=f.name) for f in traceback.extract_tb(exc.__traceback__)]))
  raise
