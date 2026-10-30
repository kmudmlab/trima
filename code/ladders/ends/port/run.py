#!/usr/bin/env python3
"""gap/direct runner: coo/run_port.py + direct modes (7-10), counters switch, range-read accessors.

Baseline modes 1-6 run unchanged algorithm code; COUNTERS=0 (default) removes diagnostic tallies.
"""
import statistics,time,argparse, fcntl, hashlib, importlib.metadata, json, os, subprocess
from pathlib import Path
import numpy as np
from device_wait import wait_device_free
from reduce import reduce_counts

HERE=Path(__file__).resolve().parent;G=HERE.parent.parent
MODES={'tricore':1,'wetric':2,'steptc':3,'btc-scalar':4,'trust-packed':5,'tricore-coo':6,'steptc-direct':7,'wetric-direct':8,'tricore-coo-direct':9,'tricore-coo-grid':10}
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(16<<20),b''):h.update(b)
    return h.hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--validated-sha');ap.add_argument('--reference',type=Path);ap.add_argument('--candidate-reference',type=Path)
    ap.add_argument('--mode',choices=MODES,required=True);ap.add_argument('--expected',type=int,required=True)
    ap.add_argument('--cores',type=int,choices=[1,11,55,110],default=110);ap.add_argument('--engines',type=int,choices=[1,2],default=2)
    ap.add_argument('--page-bytes',type=int,choices=[256,1024,4096,16384],default=1024);ap.add_argument('--reps',type=int,default=3)
    ap.add_argument('--row-cache-kib',type=int,default=16);ap.add_argument('--col-cache-kib',type=int,default=64)
    ap.add_argument('--aux-cache-kib',type=int,default=16)
    ap.add_argument('--spread',type=int,default=127);ap.add_argument('--tail',type=int,default=0);ap.add_argument('--cpu-check',action='store_true')
    ap.add_argument('--opt-level',type=int,choices=[0,1,2,3],default=3)
    ap.add_argument('--btc-adaptive',type=int,choices=[0,1],default=1);ap.add_argument('--btc-maskonly',type=int,choices=[0,1],default=1)
    ap.add_argument('--chunk-mib',type=int,default=256)
    ap.add_argument('--counters',type=int,choices=[0,1],default=0);ap.add_argument('--hash-oa',type=int,choices=[0,1],default=0)
    ap.add_argument('--hash-mix',type=int,choices=[0,1,2],default=0)
    ap.add_argument('--branchless',type=int,choices=[0,1],default=0);ap.add_argument('--lookup-width',type=int,choices=[1,2,4,8],default=1)
    ap.add_argument('--meta-stage',type=int,default=64);ap.add_argument('--arena-kib',type=int,default=64);ap.add_argument('--hash-size',type=int,default=16384)
    ap.add_argument('--tc-chunk',type=int,choices=[1,32],default=32);ap.add_argument('--tc-held',type=int,choices=[0,1],default=1);ap.add_argument('--tc-bound',type=int,choices=[0,1],default=1)
    ap.add_argument('--schedule',type=Path,required=True);ap.add_argument('--schedule-sha',required=True)
    ap.add_argument('--prepare-manifest',type=Path,required=True);ap.add_argument('--replay',type=Path,required=True)
    ap.add_argument('--validate-only',action='store_true')
    args=ap.parse_args()
    assert args.reps==3 and args.counters==0 and not args.cpu_check and args.engines==2 and args.cores==110
    if args.reps<1 or args.spread<1 or args.tail<0:raise ValueError('invalid counts')
    if args.cpu_check and args.spread!=127:raise ValueError('CPU dispatch oracle uses spread 127')
    args.out.mkdir(parents=True,exist_ok=False)
    def log(**r):
        with (args.out/'samples.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
        print(json.dumps(r),flush=True)
    lock=(Path(__file__).resolve().parents[4]/'hardware.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    wait_device_free(args.out/'device-wait-host.json','before_host_preparation')
    input_digest=sha(args.input)
    if args.validated_sha and input_digest!=args.validated_sha:raise AssertionError('input hash mismatch')
    reference=np.load(args.reference) if args.reference else None
    candidate_ref=np.load(args.candidate_reference) if args.candidate_reference else None
    auxpath=args.schedule
    manifest=json.loads(args.prepare_manifest.read_text());info=manifest['info']
    assert manifest['input_sha256']==input_digest and manifest['schedule_sha256']==args.schedule_sha
    assert sha(auxpath)==args.schedule_sha
    n,m=info['n'],info['m'];raw=np.memmap(args.input,dtype='<u4',mode='r');aux=np.memmap(auxpath,dtype='<u4',mode='r')
    arrays=[raw[2:n+3],raw[n+3:],aux];pb=args.page_bytes;pw=pb//4;rs=args.row_cache_kib*1024//pb;cs=args.col_cache_kib*1024//pb;auxslots=args.aux_cache_kib*1024//pb
    if min(rs,cs,auxslots)<1 or any(k*1024%pb for k in [args.row_cache_kib,args.col_cache_kib,args.aux_cache_kib]):raise ValueError('invalid cache sizes')
    chunk_words=args.chunk_mib*1024*1024//4
    if not 0<chunk_words<=2**28 or chunk_words%pw:raise ValueError('invalid chunk size')
    cap=max(32,info['maxdegree']);scratch_words=16384 if args.mode=='btc-scalar' else (2*cap+2049 if args.mode in ['steptc','trust-packed'] else cap+32)
    arena=args.arena_kib*256;ms=args.meta_stage;r16=lambda w:(w+15)//16*16
    if args.mode=='steptc-direct':scratch_words=sum(map(r16,[arena,ms*32,ms*4,ms+32,cap+32,64]+([args.hash_size,cap] if args.hash_oa else [1022,1022,cap])))
    if args.mode=='wetric-direct':scratch_words=sum(map(r16,[arena,ms*32,ms*4,ms,ms,ms,cap+32]))
    if args.mode=='tricore-coo-direct':scratch_words=sum(map(r16,[arena,ms*32,ms*4,64,64,32,cap+32,32,cap+16]))
    if 'direct' in args.mode and cap+48>arena:raise ValueError('rows must fit the arena')
    slots=rs+cs+auxslots
    scratch=(slots*pb+((slots+31)//32)*128+scratch_words*4+4095)//4096*4096
    if scratch*args.engines>1392*1024:raise ValueError('unsupported source capacity / SRAM budget')
    config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    config.update(info=info,source_sha256=input_digest,schedule_sha256=args.schedule_sha,l1_bytes=scratch*args.engines,
                  stage='task28_frozen_anchor_profile',timing_measured=not args.validate_only,endpoint_array=False)
    if args.mode=='btc-scalar':config['instruction_mapping']='BTC V5 bit BCSR16x32 and online matching retained; dense BMMA emulated with scalar AND/popcount. No native TT bit tensor instruction claim.'
    (args.out/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    import torch,ttnn
    log(event='environment',ttnn=importlib.metadata.version('ttnn'),numpy=np.__version__,torch=torch.__version__)
    wait_device_free(args.out/'device-wait-open.json','before_open_device');dev=ttnn.open_device(device_id=0)
    try:
        gx,gy=(1,1) if args.cores==1 else (11,args.cores//11)
        cr=ttnn.CoreRangeSet([ttnn.CoreRange(ttnn.CoreCoord(0,0),ttnn.CoreCoord(gx-1,gy-1))])
        buffers=[];groups=[]
        for data in arrays:
            group=[]
            for offset in range(0,max(1,len(data)),chunk_words):
                part=data[offset:offset+chunk_words];padded=np.zeros((max(1,(len(part)+pw-1)//pw),pw),dtype=np.uint32);padded.ravel()[:len(part)]=part
                host=ttnn.from_torch(torch.from_numpy(padded.view(np.int32)),dtype=ttnn.uint32,layout=ttnn.ROW_MAJOR_LAYOUT)
                t=ttnn.to_device(host,dev,memory_config=ttnn.DRAM_MEMORY_CONFIG);ttnn.synchronize_device(dev)
                group.append(len(buffers));buffers.append(t);del host,padded
            groups.append(group)
        output=ttnn.allocate_tensor_on_device(ttnn.Shape([args.cores*args.engines,1024]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
        log(event='upload',logical_bytes=sum(a.nbytes for a in arrays))
        tensors=buffers+[output];cta=[];setup=[]
        for j,t in enumerate(tensors):
            cta+=list(ttnn.TensorAccessorArgs(t).get_compile_time_args());off='0' if not j else f'a{j-1}.next_compile_time_args_offset()'
            setup.append(f'constexpr auto a{j}=TensorAccessorArgs<{off}>();')
            setup.append(f'const auto t{j}=TensorAccessor(a{j},get_common_arg_val<uint32_t>({4+j}),{pb if j<len(buffers) else 4096});')
        setup.append(f'const auto output=t{len(buffers)};')
        setup.append('auto read=[&](uint32_t which,uint32_t pg,uint32_t dst){switch(which){')
        for k,group in enumerate(groups):
            setup.append(f'case {k}:switch(pg/{chunk_words//pw}u){{')
            for c,j in enumerate(group):setup.append(f'case {c}:noc_async_read_tile(pg%{chunk_words//pw}u,t{j},dst);break;')
            setup.append('}break;')
        setup.append('}};')
        cp=chunk_words//pw
        setup.append('auto range=[&](uint32_t which,uint64_t lo,uint64_t hi,uint32_t dst){uint64_t pos=lo&~uint64_t(15),stop=(hi+15)&~uint64_t(15);while(pos<stop){uint32_t pg=pos/PAGE_WORDS,offset=(pos%PAGE_WORDS)*4,words=PAGE_WORDS-pos%PAGE_WORDS;if(words>stop-pos)words=stop-pos;uint64_t addr=0;switch(which){')
        for k,group in enumerate(groups):
            setup.append(f'case {k}:switch(pg/{cp}u){{')
            for c,j in enumerate(group):setup.append(f'case {c}:addr=get_noc_addr(pg%{cp}u,t{j});break;')
            setup.append('}break;')
        setup.append('}noc_async_read(addr+offset,dst,words*4);pos+=words;dst+=words*4;}};')
        source=(HERE/'port_kernel.cpp').read_text().replace('// ALGORITHMS',(HERE/'algorithms.hpp').read_text()+'\n'+(HERE/'optimized.hpp').read_text()+'\n'+(HERE/'direct.hpp').read_text()).replace('// ACCESSOR_SETUP','\n'.join(setup)).replace('// IO_INIT','IO<decltype(read),decltype(range)> io{base,tags,{0,0,0},read,range};')
        kernels=[];cbs=[]
        for i in range(args.engines):
            defines=dict(COUNTERS=args.counters,HASH_MIX=args.hash_mix,HASH_OA=args.hash_oa,BRANCHLESS=args.branchless,LOOKUP_WIDTH=args.lookup_width,META_STAGE=args.meta_stage,ARENA_WORDS=arena,HASH_SIZE=args.hash_size,TC_CHUNK=args.tc_chunk,TC_HELD=args.tc_held,TC_BOUND=args.tc_bound,BTC_ADAPTIVE=args.btc_adaptive,BTC_MASKONLY=args.btc_maskonly,OPT_LEVEL=args.opt_level,MODE=MODES[args.mode],ENGINE=i,ENGINES=args.engines,PAGE_WORDS=pw,ROW_SLOTS=rs,COL_SLOTS=cs,AUX_SLOTS=auxslots,SPREAD=args.spread,TAIL=min(args.tail,n),SOURCE_CAP=cap)
            code=''.join(f'#define {k} {v}\n' for k,v in defines.items())+source
            (args.out/f'engine{i}.cpp').write_text(code)
            kernels.append(ttnn.KernelDescriptor(kernel_source=code,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cr,compile_time_args=cta,
                common_runtime_args=[gx,args.cores,n,m]+[t.buffer_address() for t in tensors],runtime_args=[],config=ttnn.ReaderConfigDescriptor() if i==0 else ttnn.WriterConfigDescriptor()))
            cbs.append(ttnn.CBDescriptor(total_size=scratch,core_ranges=cr,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=i,data_format=ttnn.uint32,page_size=4096)]))
        (args.out/'source-manifest.json').write_text(json.dumps({str(p):sha(p) for p in [Path(__file__),HERE/'algorithms.hpp',HERE/'optimized.hpp',HERE/'direct.hpp',HERE/'port_kernel.cpp',HERE/'reduce.py',*args.out.glob('engine*.cpp')]},indent=2)+'\n')
        discovery='#include "api/dataflow/dataflow_api.h"\nvoid kernel_main(){\n constexpr auto a=TensorAccessorArgs<0>();auto out=TensorAccessor(a,get_common_arg_val<uint32_t>(0),4096);\n auto p=(uint32_t*)get_write_ptr(0);\n for(uint32_t i=0;i<2;i++) {\n  auto& cb=get_local_cb_interface(i);p[i*4]=get_write_ptr(i);p[i*4+1]=cb.fifo_size<<cb_addr_shift;\n  p[i*4+2]=cb.fifo_limit<<cb_addr_shift;p[i*4+3]=cb_addr_shift;\n }\n uint32_t id=get_absolute_logical_y()*get_common_arg_val<uint32_t>(1)+get_absolute_logical_x();\n noc_async_write_tile(id,out,(uint32_t)p);noc_async_write_barrier();\n}'
        dk=ttnn.KernelDescriptor(kernel_source=discovery,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cr,
            compile_time_args=list(ttnn.TensorAccessorArgs(output).get_compile_time_args()),common_runtime_args=[output.buffer_address(),gx],runtime_args=[],config=ttnn.ReaderConfigDescriptor())
        ttnn.generic_op(tensors,ttnn.ProgramDescriptor(kernels=[dk],cbs=cbs,semaphores=[]));ttnn.synchronize_device(dev)
        observed=ttnn.to_torch(output).numpy()[:args.cores,:8].astype(np.uint32)
        assert np.all(observed[:,[1,5]]==scratch)
        for k in [0,4]:assert np.all(observed[:,k+2]-observed[:,k]==scratch)
        (args.out/'cb-allocation.json').write_text(json.dumps(dict(total_cb_bytes=scratch*2,descriptor_bytes=[scratch,scratch],addresses=observed.tolist(),limit_bytes=1392*1024),indent=2)+'\n')
        program=ttnn.ProgramDescriptor(kernels=kernels,cbs=cbs,semaphores=[])
        times=[]
        for rep in range(1 if args.validate_only else 4):
            log(event='launch',repeat=rep,warmup=rep==0)
            started=time.perf_counter() if not args.validate_only else None
            ttnn.generic_op(tensors,program);ttnn.synchronize_device(dev)
            count,error=reduce_counts(ttnn,dev,ttnn.CoreCoord(args.cores*args.engines,1),output)
            elapsed=time.perf_counter()-started if not args.validate_only else None
            if rep and not args.validate_only:times.append(elapsed)
            a=ttnn.to_torch(output).numpy().astype(np.uint32);np.save(args.out/f'result-{rep}.npy',a)
            counts=a[:,0].astype(np.uint64)+(a[:,1].astype(np.uint64)<<32)
            if count!=args.expected or error or int(counts.sum())!=args.expected or np.any(a[:,22]) or not np.array_equal(a[:,24],np.arange(args.cores*args.engines)) or np.any(a[:,25]!=0x504f5254):raise AssertionError((count,args.expected,error,'output check'))
            if reference is not None and not np.array_equal(a[:,:2],reference[:,:2]):raise AssertionError('per-engine reference mismatch')
            # Candidates are validated in the counters-on correctness checkpoint.
            if args.cpu_check and list(map(int,counts))!=info['engine_counts']:raise AssertionError('per-engine oracle mismatch')
            metrics=[sum(int(r[2*j])+(int(r[2*j+1])<<32) for r in a) for j in range(7)]
            log(event='sample',repeat=rep,warmup=rep==0,count=count,metrics=metrics,per_engine_verified=args.cpu_check)

        (args.out/'summary.json').write_text(json.dumps(dict(status='pass',timing_measured=not args.validate_only,
          counters=0,per_owner_exact=True,endpoint_array=False,warmup_runs=0 if args.validate_only else 1,
          measured_runs=len(times),samples_s=times,median_s=statistics.median(times) if times else None,
          upload_excluded=True,boundary='launch+synchronize+4KiB reducer readback',reducer_input_pages=220,
          l1_bytes=scratch*2),indent=2)+'\n')
    finally:ttnn.close_device(dev);lock.close()
if __name__=='__main__':
 try:main()
 except BaseException as exc:
  import sys,traceback
  out=Path(sys.argv[sys.argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True)
  (out/'failure.json').write_text(json.dumps(dict(error=repr(exc),traceback=traceback.format_exc()),indent=2)+'\n')
  raise
