#!/usr/bin/env python3
"""Step B runner: frozen TRUST 2DM host (frozen-tt/trust/run_trust.py) + trust_gap_kernel.cpp switches.

Differences from the frozen host: feature switches, explicit SRAM layout, range-read accessors
(generator copied from frozen-tt/trima/run_tuned_dual.py), per-core oracle check against the
input metadata, optional exact candidate check against work_model.jsonl under --profile.
"""
import argparse,fcntl,hashlib,json,os,statistics,subprocess,sys,time
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent;E=R.parent.parent
sys.path.insert(0,str(E/'frozen-tt/trust'))
from scan import reduce_counts

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(16<<20),b''):h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--expected',type=int,required=True);ap.add_argument('--engine-counts',type=Path,help='input metadata json with per-core engine_counts')
    ap.add_argument('--reps',type=int,default=3);ap.add_argument('--cores',type=int,choices=[1,11,110],default=110)
    ap.add_argument('--page-bytes',type=int,choices=[1024,16384],default=1024);ap.add_argument('--row-cache-kib',type=int,default=16);ap.add_argument('--col-cache-kib',type=int,default=64)
    ap.add_argument('--bucket-cap',type=int,default=100);ap.add_argument('--hash-size',type=int,default=16384)
    ap.add_argument('--prune',type=int,choices=[0,1],default=0);ap.add_argument('--hash-oa',type=int,choices=[0,1],default=0)
    ap.add_argument('--direct',type=int,choices=[0,1],default=0);ap.add_argument('--lookup-width',type=int,choices=[1,4],default=1)
    ap.add_argument('--meta-stage',type=int,default=64);ap.add_argument('--arena-kib',type=int,default=64)
    ap.add_argument('--profile',action='store_true');ap.add_argument('--expected-candidates',type=int)
    ap.add_argument('--chunk-kib',type=int,default=1048576)
    args=ap.parse_args()
    assert args.lookup_width==1 or (args.direct and args.hash_oa),'grouped probes need DIRECT + HASH_OA'
    assert args.hash_size&(args.hash_size-1)==0
    args.out.mkdir(parents=True,exist_ok=False)
    def log(**r):
        with (args.out/'samples.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
        print(json.dumps({k:v for k,v in r.items() if k!='engine_results'}),flush=True)
    a=np.memmap(args.input,dtype='<u4',mode='r');n,m=map(int,a[:2]);rp=a[2:3+n];col=a[3+n:]
    degrees=np.diff(rp);maxdegree=int(degrees.max(initial=0));sourcecap=max(32,(maxdegree+31)//32*32)
    sources=int(np.count_nonzero(degrees>=2))
    if args.prune:
        # Pruning is exact only for strictly forward, sorted rows (same contract as TriMA --forward-suffix).
        src=np.repeat(np.arange(n,dtype=np.int64),degrees.astype(np.int64));c=np.asarray(col,dtype=np.int64)
        same=src[1:]==src[:-1]
        assert np.all(c>src) and np.all(c[1:][same]>c[:-1][same]),'PRUNE requires strictly forward sorted CSR'
        del src,c,same
    pb=args.page_bytes;pw=pb//4;rs=args.row_cache_kib*1024//pb;cs=args.col_cache_kib*1024//pb
    assert rs>0 and cs>0
    arena_words=args.arena_kib*256
    assert maxdegree+32<=arena_words,'every target row must fit one arena'
    off={};cur=0
    def put(name,nbytes):
        nonlocal cur;off[name]=cur;cur+=(nbytes+63)//64*64
    put('BINS_OFF',0 if args.hash_oa else 1024*4);put('TABLE_OFF',0 if args.hash_oa else 1024*args.bucket_cap*4)
    put('HASH_OFF',args.hash_size*4 if args.hash_oa else 0);put('USED_OFF',sourcecap*4 if args.hash_oa else 0)
    put('SOURCE_OFF',(sourcecap+32)*4);put('TAGS_OFF',((rs+cs+31)//32*32)*4);put('ROWC_OFF',(rs+cs)*pb)
    put('STAGE_OFF',args.meta_stage*32*4 if args.direct else 32*4);put('ARENA_OFF',arena_words*4 if args.direct else 0);put('RESULT_OFF',4096)
    scratch=(cur+4095)//4096*4096
    assert scratch*2<=1392*1024,(scratch,'L1 exceeds conservative budget')
    meta=json.loads(args.engine_counts.read_text()) if args.engine_counts else None
    config=dict({k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},n=n,m=m,source_cap=sourcecap,maxdegree=maxdegree,
                selected_sources=sources,scratch_per_engine=scratch,l1_bytes=scratch*2,offsets=off,input_sha256=sha(args.input),
                timing='launch + sync + device reduction + small readback; upload and full validation readback excluded')
    if meta:assert meta['input_sha256']==config['input_sha256']
    log(kind='config',**config)
    import torch,ttnn
    lock=(R.parent/'hardware.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    owners=subprocess.run(['fuser','/dev/tenstorrent/0'],capture_output=True,text=True)
    if owners.returncode not in (0,1) or ({int(x) for x in owners.stdout.split()}-{os.getpid()}):raise RuntimeError('device occupied')
    dev=ttnn.open_device(device_id=0)
    try:
        grid=ttnn.CoreCoord(1,1) if args.cores==1 else ttnn.CoreCoord(11,args.cores//11)
        core_set=ttnn.CoreRangeSet([ttnn.CoreRange(ttnn.CoreCoord(0,0),ttnn.CoreCoord(grid.x-1,grid.y-1))])
        def host(x):return ttnn.from_torch(torch.from_numpy(x.view(np.int32)),dtype=ttnn.uint32,layout=ttnn.ROW_MAJOR_LAYOUT)
        chunk_words=args.chunk_kib*256;chunk_pages=chunk_words//pw;buffers=[];array_buffers={};start=time.perf_counter()
        for name,data in [('row',rp),('col',col)]:
            array_buffers[name]=[]
            for offset in range(0,len(data),chunk_words):
                part=data[offset:offset+chunk_words];padded=np.zeros(((len(part)+pw-1)//pw,pw),dtype=np.uint32);padded.ravel()[:len(part)]=part
                tensor=ttnn.to_device(host(padded),dev,memory_config=ttnn.DRAM_MEMORY_CONFIG);ttnn.synchronize_device(dev)
                array_buffers[name].append(len(buffers));buffers.append(tensor)
        output=ttnn.allocate_tensor_on_device(ttnn.Shape([args.cores*2,1024]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
        log(kind='upload_complete',wall_s=time.perf_counter()-start)
        cbs=[ttnn.CBDescriptor(total_size=scratch,core_ranges=core_set,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=i,data_format=ttnn.uint32,page_size=4096)]) for i in range(2)]
        common=[0,0,output.buffer_address(),grid.x,args.cores,n,0,n,1,0]+[t.buffer_address() for t in buffers]
        cta=[]
        for tensor in buffers+[output]:cta+=list(ttnn.TensorAccessorArgs(tensor).get_compile_time_args())
        acc=[]
        for j in range(len(buffers)+1):
            o='0' if j==0 else f'a{j-1}.next_compile_time_args_offset()'
            acc.append(f'constexpr auto a{j}=TensorAccessorArgs<{o}>();')
            acc.append(f'const auto t{j}=TensorAccessor(a{j},get_common_arg_val<uint32_t>({10+j}),PAGE_BYTES);' if j<len(buffers) else f'const auto output=TensorAccessor(a{j},get_common_arg_val<uint32_t>(2),4096);')
        for name,ids in array_buffers.items():
            acc.append(f'auto read_{name}_page=[&](uint32_t pg,uint32_t dst){{switch(pg/{chunk_pages}u){{')
            for k,j in enumerate(ids):acc.append(f'case {k}:noc_async_read_tile(pg%{chunk_pages}u,t{j},dst);break;')
            acc.append('}};')
            acc.append(f'auto read_{name}_range=[&](uint64_t lo,uint64_t hi,uint32_t dst){{')
            acc.append('uint64_t pos=lo&~uint64_t(15),stop=(hi+15)&~uint64_t(15);while(pos<stop){uint32_t pg=pos/PAGE_WORDS,offset=(pos%PAGE_WORDS)*4,words=PAGE_WORDS-pos%PAGE_WORDS;if(words>stop-pos)words=stop-pos;uint64_t addr=0;')
            acc.append(f'switch(pg/{chunk_pages}u){{')
            for k,j in enumerate(ids):acc.append(f'case {k}:addr=get_noc_addr(pg%{chunk_pages}u,t{j});break;')
            acc.append('}noc_async_read(addr+offset,dst,words*4);pos+=words;dst+=words*4;}};')
        path=R/'trust_gap_kernel.cpp';source=path.read_text();assert source.count('// GENERATED_ACCESSORS')==1
        source=source.replace('// GENERATED_ACCESSORS','\n'.join(acc));kernels=[]
        for i in range(2):
            d=dict(ENGINE=i,ENGINES=2,PROFILE=int(args.profile),PAGE_BYTES=pb,PAGE_WORDS=pw,ROW_SLOTS=rs,COL_SLOTS=cs,BUCKET_CAP=args.bucket_cap,
                   SOURCE_CAP=sourcecap,HASH_SIZE=args.hash_size,PRUNE=args.prune,HASH_OA=args.hash_oa,DIRECT=args.direct,LOOKUP_WIDTH=args.lookup_width,
                   META_STAGE=args.meta_stage,ARENA_WORDS=arena_words,**off)
            code=''.join(f'#define {k} {v}\n' for k,v in d.items())+source;(args.out/f'engine{i}.cpp').write_text(code)
            kernels.append(ttnn.KernelDescriptor(kernel_source=code,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=core_set,compile_time_args=cta,
                common_runtime_args=common,runtime_args=[],config=ttnn.ReaderConfigDescriptor() if i==0 else ttnn.WriterConfigDescriptor()))
        (args.out/'manifest.json').write_text(json.dumps({str(p):sha(p) for p in [Path(__file__),path,*args.out.glob('engine*.cpp')]},indent=2))
        program=ttnn.ProgramDescriptor(kernels=kernels,semaphores=[],cbs=cbs);times=[]
        for rep in range(args.reps+1):
            t=time.perf_counter();ttnn.generic_op(buffers+[output],program);ttnn.synchronize_device(dev)
            total,err=reduce_counts(ttnn,dev,ttnn.CoreCoord(args.cores*2,1),output);elapsed=time.perf_counter()-t
            assert total==args.expected and err==0,(total,args.expected,err)
            a=ttnn.to_torch(output).numpy().astype(np.uint32)
            v=lambda r,j:int(r[2*j])+(int(r[2*j+1])<<32)
            counts=[v(r,0) for r in a];assert sum(counts)==args.expected and np.all(a[:,22]==0),a[:,22].tolist()
            assert sorted(map(int,a[:,24]))==list(range(args.cores*2))
            assert sum(v(r,1) for r in a)==sources
            if meta:assert [counts[i]+counts[i+1] for i in range(0,len(counts),2)]==meta['engine_counts'],'per-core oracle mismatch'
            metrics={k:sum(v(r,j) for r in a) for j,k in enumerate(['count','sources','candidates','row_pages','col_pages','batches'])}
            if args.profile and args.expected_candidates is not None:assert metrics['candidates']==args.expected_candidates,(metrics['candidates'],args.expected_candidates)
            log(kind='sample',repeat=rep,warmup=rep==0,count_with_reduce_s=elapsed,count=total,metrics=metrics,per_core_oracle=bool(meta))
            if rep:times.append(elapsed)
        log(kind='complete',median_s=statistics.median(times),samples=times)
        (args.out/'summary.json').write_text(json.dumps(dict(status='pass',median_s=statistics.median(times),samples_s=times,l1_bytes=scratch*2,
            prune=args.prune,hash_oa=args.hash_oa,direct=args.direct,lookup_width=args.lookup_width,profile=args.profile),indent=2)+'\n')
    finally:ttnn.close_device(dev);lock.close()
if __name__=='__main__':main()
