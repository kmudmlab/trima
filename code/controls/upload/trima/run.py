#!/usr/bin/env python3
"""Count oriented triangles with source-local SRAM hashes and CSR path traversal."""
import argparse,fcntl,hashlib,json,os,subprocess
import time,statistics
from pathlib import Path
import numpy as np
from device_wait import wait_device_free
from scan import reduce_counts

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(16<<20),b''):h.update(b)
 return h.hexdigest()

def read_csr(path):
 a=np.memmap(path,dtype='<u4',mode='r');n,m=map(int,a[:2]);assert len(a)==2+n+1+m
 rp=np.array(a[2:3+n],copy=True);col=np.array(a[3+n:],copy=True);assert rp[0]==0 and rp[-1]==m
 assert np.all(rp[1:]>=rp[:-1]) and (not m or int(col.max())<n)
 return n,m,rp,col

def cpu_reference(rp,col,begin,end,mod,rem,workers):
 total=0;sources=0;candidates=0;engine_counts=[0]*workers
 for u in range(begin+rem,end,mod):
  a=set(map(int,col[int(rp[u]):int(rp[u+1])]))
  if len(a)<2:continue
  sources+=1
  for v in a:
   b=col[int(rp[v]):int(rp[v+1])];candidates+=len(b)
   c=sum(int(w) in a for w in b);total+=c;engine_counts[((u-begin-rem)//mod)%workers]+=c
 return dict(count=total,sources=sources,candidates=candidates,engine_counts=engine_counts)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--expected',type=int)
 ap.add_argument('--reps',type=int,default=3);ap.add_argument('--engines',type=int,choices=[1,2],default=1);ap.add_argument('--cores',type=int,choices=[1,11,55,110],default=110)
 ap.add_argument('--page-bytes',type=int,choices=[256,1024,4096,16384,65536],default=1024);ap.add_argument('--row-cache-kib',type=int,default=16);ap.add_argument('--col-cache-kib',type=int,default=128)
 ap.add_argument('--cpu-reference-cache',type=Path,default=Path(__file__).resolve().parents[4]/'hash-mix/cpu-fixture-reference.json')
 ap.add_argument('--profile',action='store_true');ap.add_argument('--cpu-check',action='store_true');ap.add_argument('--begin',type=int,default=0);ap.add_argument('--end',type=int);ap.add_argument('--source-mod',type=int,default=1);ap.add_argument('--source-rem',type=int,default=0)
 ap.add_argument('--prefetch',type=int,choices=[0,1,2],default=1);ap.add_argument('--lower-bound',type=int,choices=[0,1],default=0)
 ap.add_argument('--batch',type=int,default=16);ap.add_argument('--method',choices=['merge','hash'],default='hash');ap.add_argument('--hash-size',type=int,default=8192)
 ap.add_argument('--hash-offsets',type=Path,required=False);ap.add_argument('--hash-data',type=Path,required=False);ap.add_argument('--forward-suffix',type=int,choices=[0,1],default=0)
 ap.add_argument('--chunk-kib',type=int,default=1048576,help='Maximum tensor size; CSR row and column arrays are split independently')
 ap.add_argument('--threads',type=int,default=12)
 ap.add_argument('--group',type=int,choices=[3,4,5,6,7,9],default=4)
 ap.add_argument('--max-degree',type=int,default=868)
 ap.add_argument('--lookup-width',type=int,choices=[1,2,4,8],default=1)
 ap.add_argument('--reverse-lookup',type=int,choices=[0,1],default=0)
 ap.add_argument('--bound-target',type=int,choices=[0,1],default=0)
 ap.add_argument('--hybrid-factor',type=int,choices=[0,4,8,16],default=0)
 ap.add_argument('--max-sources-per-batch',type=int,default=8)
 ap.add_argument('--compact-meta',type=int,choices=[0,1,2],default=1)
 ap.add_argument('--meta-stage',type=int,default=64)
 ap.add_argument('--pool-banks',type=int,choices=[0,1,2],default=1)
 ap.add_argument('--mask-small-rows',type=int,choices=[0,1],default=0)
 ap.add_argument('--contexts',type=int,choices=[1,2,4,8],default=2)
 ap.add_argument('--arena-kib',type=int,default=64)
 ap.add_argument('--serialize-sources',type=int,choices=[0,1],default=0)
 ap.add_argument('--duplicate-arenas',type=int,choices=[0,1],default=0)
 ap.add_argument('--validated-sha',type=str,default='f4c5caedd04d9e1054cf492473fa24bf64af685e4f4afe27cf6cd11ae5710e4f')
 ap.add_argument('--hash-mix',type=int,choices=[0,1,2],default=1)
 ap.add_argument('--probe-limit',type=int,default=8)
 ap.add_argument('--cooperative-batches',type=int,choices=[0,1,2],default=1)
 ap.add_argument('--right-tiles',type=int,choices=[0,1],default=0)
 ap.add_argument('--probe-policy',type=int,choices=[0,1,2],default=1)
 ap.add_argument('--labels',type=int,choices=[0,16,24,32],default=24)
 ap.add_argument('--no-trisc',type=int,choices=[0,1],default=0,help='gap/C: TRISC consumers acknowledge ring steps without computing; DM producers compute every lane')
 ap.add_argument('--aux-rowptr',type=int,choices=[0,1],default=0);ap.add_argument('--aux-file',type=Path);ap.add_argument('--aux-manifest',type=Path)
 ap.add_argument('--tail-merge',type=int,choices=[0,1],default=0);ap.add_argument('--pipe-meta',type=int,choices=[0,1],default=0);ap.add_argument('--merge-bytes',type=int,required=True);ap.add_argument('--stage',choices=['bridge','L5','L6','L7','T-off','mix0','mix1'],required=True)
 ap.add_argument('--original-kernel',action='store_true');ap.add_argument('--reference',type=Path);ap.add_argument('--candidate-reference',type=Path);ap.add_argument('--engine-counts',type=Path)
 args=ap.parse_args()
 assert args.hash_mix==({"mix0":0,"mix1":1}.get(args.stage,2)) and args.aux_rowptr==0 and args.hybrid_factor==0 and not args.profile and not args.labels
 assert (args.contexts,args.meta_stage,args.batch,args.arena_kib,args.page_bytes)==(2,64,128,64,16384)
 assert not args.original_kernel and args.engines==1 and args.cores==110
 wanted={'bridge':(0,1,1),'L5':(1,1,1),'L6':(1,0,1),'L7':(1,0,0),'T-off':(0,0,0),'mix0':(1,0,0),'mix1':(1,0,0)}[args.stage]
 assert (args.tail_merge,args.no_trisc,args.serialize_sources)==wanted
 assert args.pool_banks==1 and args.probe_policy==1 and args.probe_limit==8
 assert args.forward_suffix==1 and args.bound_target==1 and args.lookup_width==4 and args.group==4
 assert not args.pipe_meta and not args.cooperative_batches and not args.reverse_lookup and not args.right_tiles and not args.duplicate_arenas and not args.mask_small_rows
 args.profile=False
 args.out.mkdir(parents=True,exist_ok=False)

 reference=np.load(args.reference) if args.reference else None
 candidate_ref=np.load(args.candidate_reference) if args.candidate_reference else None
 meta=json.loads(args.engine_counts.read_text()) if args.engine_counts else None
 def log(**r):
  with (args.out/'samples.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
  print(json.dumps({k:v for k,v in r.items() if k!='engine_results'}),flush=True)
 import torch,ttnn
 lock=(Path(__file__).resolve().parents[4]/'hardware.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 wait_device_free(args.out/'device-wait-host.json','before_host_preparation')
 n,m,rp,col=read_csr(args.input);end=n if args.end is None else args.end
 input_digest=sha(args.input)
 if meta:assert input_digest==meta['input_sha256'],'input hash mismatch'
 aux_data=None;aux_staging_bytes=0;aux_manifest=None
 if args.aux_rowptr:
  assert args.aux_file and args.aux_manifest
  aux_manifest=json.loads(args.aux_manifest.read_text());assert aux_manifest['status']=='pass'
  assert aux_manifest['input_sha256']==input_digest and aux_manifest['m']==m
  assert args.aux_file.stat().st_size==8*m and sha(args.aux_file)==aux_manifest['aux_sha256']
  assert aux_manifest['max_degree']<=16416,'unsupported source prefix metadata'
  aux_data=range(2*m) # Shape only: never upload or gather aux on host.
  aux_staging_bytes=aux_manifest['max_aux_source_staging_bytes']

 if args.forward_suffix and not args.cpu_check:assert input_digest==args.validated_sha
 assert 0<=args.begin<=end<=n and 0<=args.source_rem<args.source_mod
 assert 0<n<2**31 and 0<=m<2**31,'Requires a nonempty CSR within the GPU adapter signed-32-bit limits'
 assert args.reps==3 and args.engine_counts and args.meta_stage>0
 assert not args.pool_banks or args.contexts==2, 'Pooling needs two source banks'
 # Duplicated arenas remain indexed by final ctx after the existing global
 # pooling/promotion drain; both bank reader lifetimes are retired first.
 assert args.compact_meta==1
 assert not args.duplicate_arenas or args.contexts==2
 assert args.max_sources_per_batch>0
 maxdegree=args.max_degree;sourcecap=max(32,(maxdegree+16+31)//32*32)
 sources=-1 # No CPU graph traversal for algorithm-specific metadata.
 expected=args.expected
 if args.cpu_check:
  cached=None
  if args.cpu_reference_cache.exists():
   c=json.loads(args.cpu_reference_cache.read_text());assert c['status']=='pass'
   cached=c['inputs'].get(input_digest)
   if cached is not None:
    assert (cached['n'],cached['m'],cached['cores'],cached['begin'],cached['end'],cached['source_mod'],cached['source_rem'])==(n,m,args.cores,args.begin,end,args.source_mod,args.source_rem)
    assert cached['strict_forward'];ref=cached['reference']
    log(kind='cpu_reference_reused',cache=str(args.cpu_reference_cache),cache_sha256=sha(args.cpu_reference_cache),**ref)
  if cached is None:
   if args.forward_suffix:
    for u in range(n):
     row=col[int(rp[u]):int(rp[u+1])]
     assert np.all(row>u) and np.all(row[1:]>row[:-1]),'Suffix optimization requires strict numeric orientation and sorted rows'
   ref=cpu_reference(rp,col,args.begin,end,args.source_mod,args.source_rem,args.cores*2);ref['engine_counts']=[ref['engine_counts'][2*c]+ref['engine_counts'][2*c+1] for c in range(args.cores)];log(kind='cpu_reference',**ref)
  if expected is not None:assert expected==ref['count']
  expected=ref['count']
 assert expected is not None,'Use --expected or --cpu-check'
 pb=args.page_bytes;pw=pb//4;rs=args.row_cache_kib*1024//pb;cs=args.col_cache_kib*1024//pb
 chunk_bytes=args.chunk_kib*1024
 assert 0<chunk_bytes<=1024**3 and chunk_bytes%pb==0
 chunk_words=chunk_bytes//4;chunk_pages=chunk_bytes//pb
 assert (len(rp)+chunk_words-1)//chunk_words+(len(col)+chunk_words-1)//chunk_words+(0 if aux_data is None else (len(aux_data)+chunk_words-1)//chunk_words)+10<=240, "Too many tensor chunks for runtime arguments"
 assert rs>0 and cs>0 and args.row_cache_kib*1024%pb==0 and args.col_cache_kib*1024%pb==0
 tag_words=(rs+cs+31)//32*32
 assert (maxdegree+pw-2)//pw+1<=cs, "A full row must fit the column page cache"
 assert args.max_degree>0 and args.hash_size>sourcecap-16 and args.hash_size&(args.hash_size-1)==0
 assert not args.pool_banks or 2*args.hash_size>2*sourcecap-16
 import torch,ttnn
 # Recheck after potentially long CPU validation/SHA work, immediately before open.
 wait_device_free(args.out/'device-wait-open.json','before_open_device')
 dev=ttnn.open_device(device_id=0)
 try:

  times=[]
  for epoch in range(args.reps+1):
   grid=ttnn.CoreCoord(1,1) if args.cores==1 else ttnn.CoreCoord(11,args.cores//11)
   core_set=ttnn.CoreRangeSet([ttnn.CoreRange(ttnn.CoreCoord(0,0),ttnn.CoreCoord(grid.x-1,grid.y-1))])
   mapper=ttnn.ReplicateTensorToMesh(dev)
   upload_started=time.perf_counter()
   buffers=[];array_buffers={}
   def transfer(name,padded,offset):
    tensor=ttnn.from_torch(torch.from_numpy(padded),dtype=ttnn.uint32,layout=ttnn.ROW_MAJOR_LAYOUT,device=dev,memory_config=ttnn.DRAM_MEMORY_CONFIG,mesh_mapper=mapper)
    ttnn.synchronize_device(dev);array_buffers[name].append(len(buffers));buffers.append(tensor)
   for name,data in [('row',rp),('col',col)]:
    array_buffers[name]=[];array_buffers[name+'_tail']=[]
    for offset in range(0,len(data),chunk_words):
     length=min(chunk_words,len(data)-offset);aligned=length//pw*pw
     if name=='aux':
      for key,pages in [(name,aligned//pw),(name+'_tail',int(aligned<length))]:
       if pages:
        array_buffers[key].append(len(buffers))
        buffers.append(ttnn.allocate_tensor_on_device(ttnn.Shape([pages,pw]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG))
     else:
      part=data[offset:offset+length]
      if aligned:transfer(name,part[:aligned].reshape(-1,pw),offset)
      if aligned<length:
       tail=np.zeros((1,pw),dtype=np.uint32);tail.ravel()[:length-aligned]=part[aligned:]
       transfer(name+'_tail',tail,offset+aligned)
   ttnn.synchronize_device(dev)
   upload_elapsed=time.perf_counter()-upload_started
   logical_bytes=4*(len(rp)+len(col))
   padded_bytes=sum(int(t.shape[0])*pb for t in buffers)
   log(kind="upload",repeat=epoch,warmup=epoch==0,upload_s=upload_elapsed,logical_csr_bytes=logical_bytes,padded_csr_bytes=padded_bytes)
   if epoch:times.append(upload_elapsed)
   hist_bins=args.labels**3 if args.labels else 0
   hist_bytes=hist_bins*8*5
   hist_pages=(hist_bins*8+pb-1)//pb if hist_bins else 0
   if hist_bins:
    hist_output=ttnn.allocate_tensor_on_device(ttnn.Shape([args.cores*hist_pages,pw]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
    buffers.append(hist_output)
   targetcap=sourcecap;arena_words=args.arena_kib*256
   assert arena_words>=16 and arena_words%16==0
   output=ttnn.allocate_tensor_on_device(ttnn.Shape([args.cores*args.engines,1024]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
   offsets={'SOURCE_OFFSET':1024}
   offsets['AUX_OFFSET']=offsets['SOURCE_OFFSET']+args.contexts*sourcecap*4
   offsets['META_OFFSET']=offsets['AUX_OFFSET']+aux_staging_bytes
   meta_stride=4 if args.compact_meta else 32
   offsets['STAGE_OFFSET']=offsets['META_OFFSET']
   offsets['HASH_OFFSET']=offsets['STAGE_OFFSET']+(args.meta_stage*128+((args.meta_stage+31)//16)*64)
   offsets['USED_OFFSET']=offsets['HASH_OFFSET']+args.contexts*args.hash_size*4
   offsets['SPILL_OFFSET']=offsets['USED_OFFSET']+args.contexts*sourcecap*4
   offsets['TARGET_OFFSET']=offsets['SPILL_OFFSET']
   arena_count=2*args.contexts if args.duplicate_arenas else 2
   offsets['JOBS_OFFSET']=offsets['TARGET_OFFSET']+arena_count*arena_words*4
   offsets['RESULT_OFFSET']=offsets['JOBS_OFFSET']+arena_count*args.batch*8*4
   scratch=offsets['RESULT_OFFSET']+4096
   scratch=(scratch+4095)//4096*4096
   original_scratch=scratch
   offsets['STAGE2_OFFSET']=scratch
   if args.pipe_meta:scratch+=(args.meta_stage*128+((args.meta_stage+31)//16)*64+4095)//4096*4096
   merge_bytes=((args.merge_bytes+4095)//4096*4096) if args.tail_merge else 0
   offsets['MERGE_OFFSET']=scratch
   offsets['MERGE_BYTES']=merge_bytes
   scratch+=merge_bytes*(2 if args.pipe_meta else 1)
   tail_first=(n-min(n,65536))//16*16
   tail_bytes=(((n+1+15)//16*16-tail_first)*4+64+4095)//4096*4096 if args.tail_merge else 0
   total_cb=2*scratch+tail_bytes
   assert total_cb<=1392*1024,(total_cb,'L1 exceeds conservative budget')
   config=dict(vars(args));config.update(aux_staging_bytes_per_DM=aux_staging_bytes,aux_sha256=aux_manifest['aux_sha256'] if aux_manifest else None,gap_variant=args.stage,streaming_rows=True,source_tile_capacity=sourcecap-16,packed_target_buffers=True,skip_last_row=bool(args.forward_suffix),n=n,m=m,source_cap=sourcecap,maxdegree=maxdegree,expected=expected,selected_sources=sources,scratch_per_engine=scratch,l1_bytes=total_cb,graph_l1_bytes=total_cb,tail_shared_cb_bytes=tail_bytes,merge_bytes_per_slot=merge_bytes,original_cb_bytes=original_scratch*2,histogram_bytes=hist_bytes,target_cap=targetcap,hash_bytes=0,producer_count=2,consumer_count=3,active_worker_count=5,dm_assist=True,input_sha256=input_digest,input_bytes=args.input.stat().st_size)
   config={k:str(v) if isinstance(v,Path) else v for k,v in config.items()};log(kind='config',**config);(args.out/'config.json').write_text(json.dumps(config,indent=2)+'\n')
   if args.forward_suffix and not args.cpu_check:assert config['input_sha256']==args.validated_sha
   cbs=[ttnn.CBDescriptor(total_size=scratch,core_ranges=core_set,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=i,data_format=ttnn.uint32,page_size=4096)]) for i in range(2)]
   if tail_bytes:cbs.append(ttnn.CBDescriptor(total_size=tail_bytes,core_ranges=core_set,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=2,data_format=ttnn.uint32,page_size=4096)]))
   if hist_bins:cbs.append(ttnn.CBDescriptor(total_size=hist_bytes,core_ranges=core_set,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=2,data_format=ttnn.uint32,page_size=4096)]))
   common=[0,0,output.buffer_address(),grid.x,args.cores,n,args.begin,end,args.source_mod,args.source_rem]+[t.buffer_address() for t in buffers]
   hist_arg=len(common)
   common.append(0)
   cta=[]
   for tensor in buffers+[output]:cta+=list(ttnn.TensorAccessorArgs(tensor).get_compile_time_args())
   kernel_dir=Path(__file__).resolve().parents[4]/'trima_notrisc' if args.original_kernel else Path(__file__).resolve().parent
   path=kernel_dir/'tune_reader.cpp';source=path.read_text().replace('// METADATA_PLAN_HEADER',Path(__file__).with_name('metadata_plan.hpp').read_text());kernels=[]
   accessor=[]
   for j in range(len(buffers)+1):
    offset='0' if j==0 else f'a{j-1}.next_compile_time_args_offset()'
    accessor.append(f'constexpr auto a{j}=TensorAccessorArgs<{offset}>();')
    if j<len(buffers):accessor.append(f'const auto t{j}=TensorAccessor(a{j},get_common_arg_val<uint32_t>({10+j}),PAGE_BYTES);')
    else:accessor.append(f'const auto output=TensorAccessor(a{j},get_common_arg_val<uint32_t>(2),4096);')
   for name,indices in array_buffers.items():
    tailids=array_buffers.get(name+'_tail',[]);tailpg=sum(int(buffers[i].shape[0]) for i in indices)
    accessor.append(f'auto read_{name}_page=[&](uint32_t pg,uint32_t dst){{')
    if tailids:accessor.append(f'if(pg=={tailpg}u){{noc_async_read_tile(0,t{tailids[0]},dst);return;}}')
    if len(indices)==1:accessor.append(f'noc_async_read_tile(pg,t{indices[0]},dst);')
    else:
     accessor.append(f'switch(pg/{chunk_pages}u){{')
     for j,index in enumerate(indices):accessor.append(f'case {j}:noc_async_read_tile(pg%{chunk_pages}u,t{index},dst);break;')
     accessor.append('}')
    accessor.append('};')
    accessor.append(f'auto read_{name}_range=[&](uint64_t lo,uint64_t hi,uint32_t dst){{')
    accessor.append('uint64_t pos=lo&~uint64_t(15),stop=(hi+15)&~uint64_t(15);while(pos<stop){uint32_t pg=pos/PAGE_WORDS,offset=(pos%PAGE_WORDS)*4,words=PAGE_WORDS-pos%PAGE_WORDS;if(words>stop-pos)words=stop-pos;uint64_t addr=0;')
    if tailids:accessor.append(f'if(pg=={tailpg}u)addr=get_noc_addr(0,t{tailids[0]});else{{')
    if len(indices)==1:accessor.append(f'addr=get_noc_addr(pg,t{indices[0]});')
    else:
     accessor.append(f'switch(pg/{chunk_pages}u){{')
     for j,index in enumerate(indices):accessor.append(f'case {j}:addr=get_noc_addr(pg%{chunk_pages}u,t{index});break;')
     accessor.append('}')
    if tailids:accessor.append('}')
    index=0 if name.startswith('row') else 2 if name.startswith('aux') else 1
    counters='' if args.original_kernel else f'if(PROFILE){{++io_requests[{index}];io_bytes[{index}]+=words*4;}}'
    accessor.append('noc_async_read(addr+offset,dst,words*4);'+counters+'pos+=words;dst+=words*4;}};')
   assert source.count('// GENERATED_ACCESSORS')==1
   source=source.replace('// GENERATED_ACCESSORS','\n'.join(accessor)+(f'\nconst auto histogram=t{len(buffers)-1};' if hist_bins else ''))
   defines=dict(TAIL_MERGE=args.tail_merge,PIPE_META=args.pipe_meta,AUX_ROWPTR=args.aux_rowptr,NO_TRISC=args.no_trisc,HIST_BINS=hist_bins,LABELS=args.labels,HIST_BASE_ARG=hist_arg,HIST_PAGES=hist_pages,PROBE_LIMIT=args.probe_limit,HASH_MIX=args.hash_mix,POOL_BANKS=int(args.contexts==2),MAX_BATCH_SOURCES=args.max_sources_per_batch,COMPACT_META=args.compact_meta,META_STRIDE=meta_stride,META_STAGE=args.meta_stage,SERIALIZE_SOURCES=0,DUPLICATE_ARENAS=args.duplicate_arenas,RING_SLOTS=4 if args.duplicate_arenas else 2,CONTEXTS=args.contexts,ARENA_WORDS=arena_words,BOUND_TARGET=args.bound_target,HYBRID_FACTOR=args.hybrid_factor,PROFILE=int(args.profile),LOOKUP_WIDTH=args.lookup_width,REVERSE_LOOKUP=args.reverse_lookup,GROUP=args.group,CONSUMER_SLOTS=2 if args.group==9 else 1,ENGINES=1,PAGE_BYTES=pb,PAGE_WORDS=pw,SOURCE_CAP=sourcecap,TARGET_CAP=targetcap,FORWARD_SUFFIX=args.forward_suffix,BATCH=args.batch,HASH_SIZE=args.hash_size,SPIN_CAP=1000000000,**offsets)
   prefix=''.join(f'#define {k} {v}\n' for k,v in defines.items())
   discover='#include "api/dataflow/dataflow_api.h"\nvoid kernel_main(){constexpr auto a=TensorAccessorArgs<0>();auto o=TensorAccessor(a,get_common_arg_val<uint32_t>(2),4096);uint32_t p=get_write_ptr(0);((uint32_t*)p)[0]=p;((uint32_t*)p)[1]=get_write_ptr(1);uint32_t id=get_absolute_logical_y()*get_common_arg_val<uint32_t>(3)+get_absolute_logical_x();noc_async_write_tile(id,o,p);noc_async_write_barrier();}'
   if tail_bytes:discover=discover.replace('((uint32_t*)p)[1]=get_write_ptr(1);','((uint32_t*)p)[1]=get_write_ptr(1);((uint32_t*)p)[2]=get_write_ptr(2);((volatile uint32_t*)get_write_ptr(2))[0]=0;')
   if hist_bins:discover=discover.replace('((uint32_t*)p)[1]=get_write_ptr(1);','((uint32_t*)p)[1]=get_write_ptr(1);((uint32_t*)p)[2]=get_write_ptr(2);')
   kd=ttnn.KernelDescriptor(kernel_source=discover,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=core_set,compile_time_args=list(ttnn.TensorAccessorArgs(output).get_compile_time_args()),common_runtime_args=common,runtime_args=[],config=ttnn.ReaderConfigDescriptor())
   ttnn.generic_op(buffers+[output],ttnn.ProgramDescriptor(kernels=[kd],semaphores=[],cbs=cbs));ttnn.synchronize_device(dev)
   addresses=ttnn.to_torch(output).numpy()[:,:3 if (hist_bins or tail_bytes) else 2];assert np.all(addresses==addresses[0]);common[0]=int(addresses[0,0]);common[1]=int(addresses[0,1])
   (args.out/f'cb-allocation-{epoch}.json').write_text(json.dumps(dict(cb_addresses=addresses.tolist(),descriptor_bytes=[scratch,scratch]+([tail_bytes] if tail_bytes else []),total_cb_bytes=total_cb,aux_staging_bytes_per_DM=aux_staging_bytes,l1_limit_bytes=1392*1024),indent=2)+'\n')
   if hist_bins:common[hist_arg]=int(addresses[0,2])
   cfg=ttnn.ComputeConfigDescriptor();cfg.fp32_dest_acc_en=True;cfg.dst_full_sync_en=False;cfg.unpack_to_dest_mode=[ttnn.UnpackToDestMode.UnpackToDestFp32]*64
   workerpath=kernel_dir/'tune_worker.cpp';worker=workerpath.read_text()
   for name,code,kernel_config,ct in [('reader','#define CHANNEL 0\n'+source,ttnn.ReaderConfigDescriptor(),cta),('writer','#define CHANNEL 1\n'+source,ttnn.WriterConfigDescriptor(),cta),('compute',worker,cfg,[])]:
    code=prefix+code;(args.out/f'{name}.cpp').write_text(code)
    kernels.append(ttnn.KernelDescriptor(kernel_source=code,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=core_set,compile_time_args=ct,common_runtime_args=common,runtime_args=[],config=kernel_config))
   (args.out/'manifest.json').write_text(json.dumps({str(p):sha(p) for p in [Path(__file__),path,workerpath,Path(__file__).with_name('scan.py'),Path(__file__).with_name('metadata_plan.hpp'),*args.out.glob('*.cpp')]},indent=2))
   program=ttnn.ProgramDescriptor(kernels=kernels,semaphores=[],cbs=cbs)
   for rep in [epoch]:
    log(kind='launch',repeat=rep,warmup=rep==0)
    epochcommon=list(common);epochcommon[5]=(epoch+1)|(args.serialize_sources<<31)|(args.pool_banks<<30)|(args.mask_small_rows<<29)|(args.probe_policy<<28)|(args.right_tiles<<27)|(args.cooperative_batches<<26)
    for kd in kernels:kd.common_runtime_args=epochcommon
    program=ttnn.ProgramDescriptor(kernels=kernels,semaphores=[],cbs=cbs)
    ttnn.generic_op(buffers+[output],program);ttnn.synchronize_device(dev);device_total,device_error=reduce_counts(ttnn,dev,grid,output)
    if hist_bins:
     histogram_words=ttnn.to_torch(hist_output).numpy().reshape(args.cores,-1)[:,:hist_bins*2].copy()
     histogram_cores=histogram_words[:,0::2].astype(np.uint64)+(histogram_words[:,1::2].astype(np.uint64)<<32)
     histogram_total=histogram_cores.sum(axis=0,dtype=np.uint64)
    if hist_bins:
     assert int(histogram_total.sum(dtype=np.uint64))==expected
     np.savez_compressed(args.out/f'histogram-{epoch}.npz',cores=histogram_cores,total=histogram_total)
     log(kind='histogram',epoch=epoch,labels=args.labels,bins=hist_bins,total=int(histogram_total.sum()),sha256=hashlib.sha256(histogram_total.tobytes()).hexdigest())
    a=ttnn.to_torch(output).numpy().astype(np.uint32)
    np.save(args.out/f"raw-{epoch}.npy",a)
    if reference is not None:assert np.array_equal(a[:,:2],reference[:,:2]),'per-core reference mismatch'
    if candidate_ref is not None:assert np.array_equal(a[:,26:28],candidate_ref[:,26:28]),'per-core candidate mismatch'
    assert device_total==expected and device_error==0
    counts=[int(r[0])+(int(r[1])<<32) for r in a];sc=sum(int(r[2])+(int(r[3])<<32) for r in a)
    assert np.all(a[:,22]==0),a[:,22].tolist()
    assert sorted(map(int,a[:,24]))==list(range(args.cores*args.engines))
    assert sum(counts)==expected,(sum(counts),expected)
    if meta:assert counts==meta['engine_counts'],'per-core metadata oracle'
    assert (not args.cpu_check or not args.profile) or sc==ref["sources"],(sc,sources)
    metrics={k:sum(int(r[2*j])+(int(r[2*j+1])<<32) for r in a) for j,k in enumerate(['count','sources','source_edges','neighbor_rows','merge_comparisons','row_pages','col_pages','row_requests','col_page_requests','range_rejected','reserved'])}
    if args.cpu_check:assert counts==ref['engine_counts'],(counts,ref['engine_counts'])
    log(kind='sample',repeat=epoch,warmup=epoch==0,count=sum(counts),max_degree=int(a[:,23].max()),metrics=metrics,engine_results=a[:,:25].tolist(),validation_outside_upload=True)
    log(kind='traversal',epoch=epoch,candidates=sum(int(r[26])+(int(r[27])<<32) for r in a),profile=args.profile)
   for tensor in buffers+[output]:ttnn.deallocate(tensor)

  (args.out/'summary.json').write_text(json.dumps(dict(status='pass',per_owner_exact=True,aux_device_built=False,timing_measured=True,counters=0,warmup_runs=1,measured_runs=len(times),samples_s=times,median_s=statistics.median(times),metric="csr_host_to_device_upload",logical_csr_bytes=logical_bytes,padded_csr_bytes=padded_bytes,upload_excluded=False,boundary="host views/tail padding + torch wrapper + CSR DRAM allocation/from_torch transfer + synchronize; excludes file load/orientation/device open/Count",l1_bytes=config['l1_bytes'],profile=args.profile,stage=args.stage,active_source_contexts=1 if args.serialize_sources else 2,physical_contexts=2,control_name='two_physical_banks_serialized' if args.serialize_sources else 'two_physical_banks_overlapped',not_task28_physical_ctx1=True),indent=2)+'\n')
 finally:
  ttnn.close_device(dev);lock.close()
if __name__=='__main__':
 try:
  main()
 except BaseException as exc:
  import sys,re,traceback
  out=Path(sys.argv[sys.argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True)
  message='\n'.join(line for line in str(exc).splitlines() if not re.search(r'(?i)(duration|elapsed|\b[0-9]+[.]?[0-9]*\s*(ms|seconds|secs)\b|[0-9]{2}:[0-9]{2}:[0-9]{2})',line))
  (out/'failure.json').write_text(json.dumps(dict(error_type=type(exc).__name__,error=message,frames=[dict(file=f.filename,line=f.lineno,function=f.name) for f in traceback.extract_tb(exc.__traceback__)]),indent=2)+'\n')
  raise

