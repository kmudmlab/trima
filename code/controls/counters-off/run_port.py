#!/usr/bin/env python3
"""Initial algorithm-preserving scalar ports; no claim of fully tuned ports."""
import argparse, fcntl, hashlib, importlib.metadata, json, os, statistics, subprocess, time
from pathlib import Path
import numpy as np
from reduce import reduce_counts
HERE=Path(__file__).resolve().parent
MODES={'tricore':1,'wetric':2,'steptc':3,'btc-scalar':4,'trust-packed':5}
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(16<<20),b''):h.update(b)
    return h.hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--mode',choices=MODES,required=True);ap.add_argument('--expected',type=int,required=True)
    ap.add_argument('--cores',type=int,choices=[1,11,55,110],default=110);ap.add_argument('--engines',type=int,choices=[1,2],default=2)
    ap.add_argument('--page-bytes',type=int,choices=[256,1024,4096],default=1024);ap.add_argument('--reps',type=int,default=3)
    ap.add_argument('--row-cache-kib',type=int,default=16);ap.add_argument('--col-cache-kib',type=int,default=64)
    ap.add_argument('--aux-cache-kib',type=int,default=16)
    ap.add_argument('--spread',type=int,default=127);ap.add_argument('--tail',type=int,default=0);ap.add_argument('--cpu-check',action='store_true')
    ap.add_argument('--opt-level',type=int,choices=[0,1,2,3],default=3)
    ap.add_argument('--btc-adaptive',type=int,choices=[0,1],default=1);ap.add_argument('--btc-maskonly',type=int,choices=[0,1],default=1)
    ap.add_argument('--chunk-mib',type=int,default=256);args=ap.parse_args()
    if args.reps<1 or args.spread<1 or args.tail<0:raise ValueError('invalid counts')
    if args.cpu_check and args.spread!=127:raise ValueError('CPU dispatch oracle uses spread 127')
    args.out.mkdir(parents=True,exist_ok=False)
    def log(**r):
        with (args.out/'samples.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
        print(json.dumps(r),flush=True)
    start=time.perf_counter();auxpath=args.out/'aux.bin'
    command=[str(HERE/f'prepare-{args.opt_level}'),str(args.input),str(auxpath),str(MODES[args.mode]),str(args.tail)]
    if args.cpu_check:command.append(str(args.cores*args.engines))
    info=json.loads(subprocess.check_output(command,text=True));prep_s=time.perf_counter()-start
    if args.cpu_check and info['count']!=args.expected:raise ValueError('CPU algorithm != independent expected')
    n,m=info['n'],info['m'];raw=np.memmap(args.input,dtype='<u4',mode='r');aux=np.memmap(auxpath,dtype='<u4',mode='r')
    arrays=[raw[2:n+3],raw[n+3:],aux];pb=args.page_bytes;pw=pb//4;rs=args.row_cache_kib*1024//pb;cs=args.col_cache_kib*1024//pb;auxslots=args.aux_cache_kib*1024//pb
    if min(rs,cs,auxslots)<1 or any(k*1024%pb for k in [args.row_cache_kib,args.col_cache_kib,args.aux_cache_kib]):raise ValueError('invalid cache sizes')
    chunk_words=args.chunk_mib*1024*1024//4
    if not 0<chunk_words<=2**28 or chunk_words%pw:raise ValueError('invalid chunk size')
    cap=max(32,info['maxdegree']);scratch_words=16384 if args.mode=='btc-scalar' else (2*cap+2049 if args.mode in ['steptc','trust-packed'] else cap+32)
    slots=rs+cs+auxslots
    scratch=(slots*pb+((slots+31)//32)*128+scratch_words*4+4095)//4096*4096
    if scratch*args.engines>1392*1024:raise ValueError('unsupported source capacity / SRAM budget')
    config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    config.update(info=info,source_sha256=sha(args.input),aux_sha256=sha(auxpath),preparation_s=prep_s,l1_bytes=scratch*args.engines,
                  stage='gap_nocounters_20261022',timing='Count = launch + sync + device reduction + small readback; prep/upload/full validation excluded',
                  counters='off (diagnostic tallies compiled to no-ops; count/error real)',limitations='Static two-DM execution. Counters DISABLED in this copy; same scratch allocation across opt levels. No final optimality claim.')
    if args.mode=='btc-scalar':config['instruction_mapping']='BTC V5 bit BCSR16x32 and online matching retained; dense BMMA emulated with scalar AND/popcount. No native TT bit tensor instruction claim.'
    (args.out/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    lock=(HERE.parent.parent/'hardware.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    owners=subprocess.run(['fuser','/dev/tenstorrent/0'],capture_output=True,text=True)
    if owners.returncode not in (0,1) or ({int(x) for x in owners.stdout.split()}-{os.getpid()}):raise RuntimeError('device occupied or ownership unknown')
    import torch,ttnn
    log(event='environment',ttnn=importlib.metadata.version('ttnn'),numpy=np.__version__,torch=torch.__version__)
    dev=ttnn.open_device(device_id=0)
    try:
        gx,gy=(1,1) if args.cores==1 else (11,args.cores//11)
        cr=ttnn.CoreRangeSet([ttnn.CoreRange(ttnn.CoreCoord(0,0),ttnn.CoreCoord(gx-1,gy-1))])
        buffers=[];groups=[];upstart=time.perf_counter()
        for data in arrays:
            group=[]
            for offset in range(0,max(1,len(data)),chunk_words):
                part=data[offset:offset+chunk_words];padded=np.zeros((max(1,(len(part)+pw-1)//pw),pw),dtype=np.uint32);padded.ravel()[:len(part)]=part
                host=ttnn.from_torch(torch.from_numpy(padded.view(np.int32)),dtype=ttnn.uint32,layout=ttnn.ROW_MAJOR_LAYOUT)
                t=ttnn.to_device(host,dev,memory_config=ttnn.DRAM_MEMORY_CONFIG);ttnn.synchronize_device(dev)
                group.append(len(buffers));buffers.append(t);del host,padded
            groups.append(group)
        output=ttnn.allocate_tensor_on_device(ttnn.Shape([args.cores*args.engines,1024]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
        log(event='upload',seconds=time.perf_counter()-upstart,logical_bytes=sum(a.nbytes for a in arrays))
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
        source=(HERE/'port_kernel.cpp').read_text().replace('// ALGORITHMS',(HERE/'algorithms.hpp').read_text()+'\n'+(HERE/'optimized.hpp').read_text()).replace('// ACCESSOR_SETUP','\n'.join(setup)).replace('// IO_INIT','IO<decltype(read)> io{base,tags,{0,0,0},read};')
        kernels=[];cbs=[]
        for i in range(args.engines):
            defines=dict(BTC_ADAPTIVE=args.btc_adaptive,BTC_MASKONLY=args.btc_maskonly,OPT_LEVEL=args.opt_level,MODE=MODES[args.mode],ENGINE=i,ENGINES=args.engines,PAGE_WORDS=pw,ROW_SLOTS=rs,COL_SLOTS=cs,AUX_SLOTS=auxslots,SPREAD=args.spread,TAIL=min(args.tail,n),SOURCE_CAP=cap)
            code=''.join(f'#define {k} {v}\n' for k,v in defines.items())+source
            (args.out/f'engine{i}.cpp').write_text(code)
            kernels.append(ttnn.KernelDescriptor(kernel_source=code,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cr,compile_time_args=cta,
                common_runtime_args=[gx,args.cores,n,m]+[t.buffer_address() for t in tensors],runtime_args=[],config=ttnn.ReaderConfigDescriptor() if i==0 else ttnn.WriterConfigDescriptor()))
            cbs.append(ttnn.CBDescriptor(total_size=scratch,core_ranges=cr,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=i,data_format=ttnn.uint32,page_size=4096)]))
        (args.out/'source-manifest.json').write_text(json.dumps({str(p):sha(p) for p in [HERE/'run_port.py',HERE/'algorithms.hpp',HERE/'optimized.hpp',HERE/f'prepare-{args.opt_level}',HERE/'port_kernel.cpp',HERE/'prepare.cpp',HERE/'reduce.py',*args.out.glob('engine*.cpp')]},indent=2)+'\n')
        program=ttnn.ProgramDescriptor(kernels=kernels,cbs=cbs,semaphores=[]);times=[]
        for rep in range(args.reps+1):
            log(event='launch',repeat=rep,warmup=rep==0);start=time.perf_counter()
            ttnn.generic_op(tensors,program);ttnn.synchronize_device(dev)
            count,error=reduce_counts(ttnn,dev,ttnn.CoreCoord(args.cores*args.engines,1),output);seconds=time.perf_counter()-start
            a=ttnn.to_torch(output).numpy().astype(np.uint32);np.save(args.out/f'result-{rep}.npy',a)
            counts=a[:,0].astype(np.uint64)+(a[:,1].astype(np.uint64)<<32)
            if count!=args.expected or error or int(counts.sum())!=args.expected or np.any(a[:,22]) or not np.array_equal(a[:,24],np.arange(args.cores*args.engines)) or np.any(a[:,25]!=0x504f5254):raise AssertionError((count,args.expected,error,'output check'))
            if args.cpu_check and list(map(int,counts))!=info['engine_counts']:raise AssertionError('per-engine oracle mismatch')
            metrics=[sum(int(r[2*j])+(int(r[2*j+1])<<32) for r in a) for j in range(7)]
            log(event='sample',repeat=rep,warmup=rep==0,count=count,seconds=seconds,metrics=metrics,per_engine_verified=args.cpu_check)
            if rep:times.append(seconds)
        (args.out/'summary.json').write_text(json.dumps(dict(status='pass',mode=args.mode,count=args.expected,median_s=statistics.median(times),samples_s=times,l1_bytes=scratch*args.engines,stage='gap_nocounters_20261022'),indent=2)+'\n')
        log(event='complete',median_s=statistics.median(times))
    finally:ttnn.close_device(dev);lock.close()
if __name__=='__main__':main()
