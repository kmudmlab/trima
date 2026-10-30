#!/usr/bin/env python3
"""StepTC single-context 2x2. New process/cell, fixed CBs, fail-closed vectors."""
import argparse,fcntl,hashlib,json,os,statistics,struct,subprocess,sys,time
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
DIRECT=HERE.parent/'suite-v1/code/direct'
sys.path.insert(0,str(DIRECT))
from reduce import reduce_counts
from run_port import sha

def elf_record(path):
    data=path.read_bytes()
    assert data[:5]==b'\x7fELF\x01',path
    phoff=struct.unpack_from('<I',data,28)[0];entry,num=struct.unpack_from('<HH',data,42)
    segments=[]
    for i in range(num):
        kind,off,vaddr,paddr,filesz,memsz,flags,align=struct.unpack_from('<8I',data,phoff+i*entry)
        if kind==1:segments.append(dict(address=vaddr,file_bytes=filesz,memory_bytes=memsz,flags=flags))
    return dict(path=str(path),file_bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),segments=segments)

def main():
    ap=argparse.ArgumentParser()
    for key in ['input','out']:ap.add_argument('--'+key,type=Path,required=True)
    ap.add_argument('--expected',type=int,required=True);ap.add_argument('--cell',choices=['C0','C1','D0','D1'],required=True)
    ap.add_argument('--cores',type=int,choices=[1,11,110],default=110);ap.add_argument('--counters',type=int,choices=[0,1],default=0)
    ap.add_argument('--reps',type=int,default=3);ap.add_argument('--reference',type=Path);ap.add_argument('--candidate-reference',type=Path)
    ap.add_argument('--validated-sha');ap.add_argument('--cpu-check',action='store_true');ap.add_argument('--stress',type=int,default=0)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    def log(**record):
        with (args.out/'samples.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
        print(json.dumps(record),flush=True)
    digest=sha(args.input)
    if args.validated_sha and digest!=args.validated_sha:raise AssertionError('input hash mismatch: stop')
    if not args.cpu_check and args.reference is None:raise ValueError('verified per-engine reference required')
    if args.counters and not args.cpu_check and args.candidate_reference is None:raise ValueError('verified candidate reference required')
    if args.stress and not args.cpu_check:raise ValueError('stress only permitted for fixtures')
    prep=DIRECT/'prepare-L2-c32-h1-b1';auxpath=args.out/'aux.bin'
    command=[str(prep),str(args.input),str(auxpath),'7','0']
    if args.cpu_check:command.append(str(args.cores*2))
    info=json.loads(subprocess.check_output(command,text=True))
    if info['maxdegree']>2240:raise ValueError('approved source capacity exceeded')
    if args.cpu_check and info['count']!=args.expected:raise AssertionError('CPU independent count')
    oracle=None
    if args.cpu_check:
        binary=HERE.parent/'trisc-v1/cpu-v1/cpu_check'
        oracle=json.loads(subprocess.check_output([str(binary),str(args.input),str(auxpath),str(args.cores*2)],text=True))['engines']
    reference=np.load(args.reference) if args.reference else None
    candidate_ref=np.load(args.candidate_reference) if args.candidate_reference else None
    n,m=info['n'],info['m'];raw=np.memmap(args.input,dtype='<u4',mode='r');aux=np.memmap(auxpath,dtype='<u4',mode='r')
    arrays=[raw[2:n+3],raw[n+3:],aux];chunk_words=256*1024*1024//4;pw=256
    config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    config.update(info=info,source_sha256=digest,aux_sha256=sha(auxpath),l1_design_bytes=688128,
                  timing='launch+sync+device reduction+small readback; full validation outside timer')
    (args.out/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    lock=(HERE.parents[1]/'hardware.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    owners=subprocess.run(['fuser','/dev/tenstorrent/0'],capture_output=True,text=True)
    if owners.returncode not in (0,1) or ({int(x) for x in owners.stdout.split()}-{os.getpid()}):raise RuntimeError('device occupied')
    import torch,ttnn
    dev=ttnn.open_device(device_id=0)
    try:
        gx,gy=(1,1) if args.cores==1 else (11,args.cores//11)
        cr=ttnn.CoreRangeSet([ttnn.CoreRange(ttnn.CoreCoord(0,0),ttnn.CoreCoord(gx-1,gy-1))])
        buffers=[];groups=[]
        for data in arrays:
            group=[]
            for offset in range(0,max(1,len(data)),chunk_words):
                part=data[offset:offset+chunk_words];padded=np.zeros((max(1,(len(part)+pw-1)//pw),pw),dtype=np.uint32);padded.ravel()[:len(part)]=part
                host=ttnn.from_torch(torch.from_numpy(padded.view(np.int32)),dtype=ttnn.uint32,layout=ttnn.ROW_MAJOR_LAYOUT)
                tensor=ttnn.to_device(host,dev,memory_config=ttnn.DRAM_MEMORY_CONFIG);ttnn.synchronize_device(dev)
                group.append(len(buffers));buffers.append(tensor);del host,padded
            groups.append(group)
        output=ttnn.allocate_tensor_on_device(ttnn.Shape([args.cores*2,1024]),ttnn.uint32,ttnn.ROW_MAJOR_LAYOUT,dev,ttnn.DRAM_MEMORY_CONFIG)
        tensors=buffers+[output];common=[gx,args.cores,n,m,0,0,0]+[t.buffer_address() for t in tensors]
        cbs=[ttnn.CBDescriptor(total_size=344064,core_ranges=cr,format_descriptors=[ttnn.CBFormatDescriptor(buffer_index=i,data_format=ttnn.uint32,page_size=4096)]) for i in range(2)]
        discovery='''#include "api/dataflow/dataflow_api.h"
void kernel_main(){
 constexpr auto a=TensorAccessorArgs<0>();auto out=TensorAccessor(a,get_common_arg_val<uint32_t>(0),4096);
 auto p=(uint32_t*)get_write_ptr(0);
 for(uint32_t i=0;i<2;i++) {
   auto& cb=get_local_cb_interface(i);p[i*4]=get_write_ptr(i);p[i*4+1]=cb.fifo_size<<cb_addr_shift;
   p[i*4+2]=cb.fifo_limit<<cb_addr_shift;p[i*4+3]=cb_addr_shift;
   auto sy=(volatile uint32_t*)(get_write_ptr(i)+4096);for(uint32_t j=0;j<1024;j++){sy[j]=0;}
 }
 uint32_t id=get_absolute_logical_y()*get_common_arg_val<uint32_t>(1)+get_absolute_logical_x();
 noc_async_write_tile(id,out,(uint32_t)p);noc_async_write_barrier();
}'''
        kd=ttnn.KernelDescriptor(kernel_source=discovery,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cr,
            compile_time_args=list(ttnn.TensorAccessorArgs(output).get_compile_time_args()),common_runtime_args=[output.buffer_address(),gx],runtime_args=[],config=ttnn.ReaderConfigDescriptor())
        ttnn.generic_op(tensors,ttnn.ProgramDescriptor(kernels=[kd],cbs=cbs,semaphores=[]));ttnn.synchronize_device(dev)
        addresses=ttnn.to_torch(output).numpy()[:args.cores,:8].astype(np.uint32)
        np.save(args.out/'cb-discovery.npy',addresses)
        assert np.all(addresses==addresses[0]) and np.all(addresses[:,[1,5]]==344064),addresses.tolist()
        for k in [0,4]:assert np.all(addresses[:,k+2]-addresses[:,k]==344064),addresses.tolist()
        common[5],common[6]=map(int,addresses[0,[0,4]])
        assert common[5]+344064<=common[6] or common[6]+344064<=common[5]
        log(event='cb_discovery',per_channel_bytes=[344064,344064],total_bytes=688128,observed=addresses[0].tolist())
        cta=[];setup=[]
        for j,t in enumerate(tensors):
            cta+=list(ttnn.TensorAccessorArgs(t).get_compile_time_args());off='0' if j==0 else f'a{j-1}.next_compile_time_args_offset()'
            setup.extend([f'constexpr auto a{j}=TensorAccessorArgs<{off}>();',f'const auto t{j}=TensorAccessor(a{j},get_common_arg_val<uint32_t>({7+j}),{1024 if j<len(buffers) else 4096});'])
        setup.append(f'const auto output=t{len(buffers)};')
        cp=chunk_words//pw
        setup.append('auto read_page=[&](uint32_t which,uint32_t pg,uint32_t dst){switch(which){')
        for k,group in enumerate(groups):
            setup.append(f'case {k}:switch(pg/{cp}u){{')
            for c,j in enumerate(group):setup.append(f'case {c}:noc_async_read_tile(pg%{cp}u,t{j},dst);break;')
            setup.append('}break;')
        setup.append('}};')
        setup.append('auto range_read=[&](uint32_t which,uint64_t lo,uint64_t hi,uint32_t dst){uint64_t p=lo&~uint64_t(15),stop=(hi+15)&~uint64_t(15);while(p<stop){uint32_t pg=p/256,offset=p%256,words=256-offset;if(words>stop-p){words=stop-p;}uint64_t addr=0;switch(which){')
        for k,group in enumerate(groups):
            setup.append(f'case {k}:switch(pg/{cp}u){{')
            for c,j in enumerate(group):setup.append(f'case {c}:addr=get_noc_addr(pg%{cp}u,t{j});break;')
            setup.append('}break;')
        setup.append('}noc_async_read(addr+offset*4,dst,words*4);p+=words;dst+=words*4;}};')
        shared=(HERE/'step_shared.hpp').read_text()
        prefix=f'#define COUNTERS {args.counters}\n#define TRISC_ON {int(args.cell[1])}\n#define DIRECT {int(args.cell[0]=="D")}\n#define STRESS {args.stress}\n'
        reader=(HERE/'step_reader.cpp').read_text().replace('// SHARED',shared).replace('// ACCESSORS','\n'.join(setup))
        worker=(HERE/'step_worker.cpp').read_text().replace('// SHARED',shared)
        cfg=ttnn.ComputeConfigDescriptor();cfg.fp32_dest_acc_en=True;cfg.dst_full_sync_en=False;cfg.unpack_to_dest_mode=[ttnn.UnpackToDestMode.UnpackToDestFp32]*64
        kernels=[]
        for name,body,configuration,ct in [('reader','#define CHANNEL 0\n'+reader,ttnn.ReaderConfigDescriptor(),cta),('writer','#define CHANNEL 1\n'+reader,ttnn.WriterConfigDescriptor(),cta),('worker',worker,cfg,[])]:
            code=prefix+body;(args.out/f'{name}.cpp').write_text(code)
            kernels.append(ttnn.KernelDescriptor(kernel_source=code,source_type=ttnn.KernelDescriptor.SourceType.SOURCE_CODE,core_ranges=cr,compile_time_args=ct,common_runtime_args=common,runtime_args=[],config=configuration))
        (args.out/'manifest.json').write_text(json.dumps({str(p):sha(p) for p in [Path(__file__),HERE/'step_reader.cpp',HERE/'step_worker.cpp',HERE/'step_shared.hpp',prep,*args.out.glob('*.cpp')]},indent=2)+'\n')
        cache=Path.home()/'.cache/tt-metal-cache';before={str(p):p.stat().st_mtime_ns for p in cache.rglob('*.elf')};times=[]
        for rep in range(args.reps+1):
            common[4]=rep+1
            for kernel in kernels:kernel.common_runtime_args=list(common)
            program=ttnn.ProgramDescriptor(kernels=kernels,cbs=cbs,semaphores=[])
            log(event='launch',repeat=rep,warmup=rep==0);start=time.perf_counter()
            ttnn.generic_op(tensors,program);ttnn.synchronize_device(dev)
            count,error=reduce_counts(ttnn,dev,ttnn.CoreCoord(args.cores*2,1),output);elapsed=time.perf_counter()-start
            if rep==0:
                records=[elf_record(p) for p in cache.rglob('*.elf') if before.get(str(p))!=p.stat().st_mtime_ns and '/trisc' in str(p)]
                (args.out/'new-trisc-elfs.json').write_text(json.dumps(records,indent=2)+'\n');log(event='compiled_trisc',binaries=records)
            a=ttnn.to_torch(output).numpy().astype(np.uint32);np.save(args.out/f'result-{rep}.npy',a)
            counts=a[:,0].astype(np.uint64)+(a[:,1].astype(np.uint64)<<32)
            candidates=a[:,4].astype(np.uint64)+(a[:,5].astype(np.uint64)<<32)
            assert count==args.expected and not error and int(counts.sum())==args.expected and not np.any(a[:,22]),(count,args.expected,error,a[:,22].tolist())
            assert np.array_equal(a[:,24],np.arange(args.cores*2)) and np.all(a[:,25]==0x53545243)
            if oracle is not None:
                assert counts.tolist()==[r[0] for r in oracle],'CPU per-engine mismatch'
                if args.counters:assert candidates.tolist()==[r[1] for r in oracle],'CPU candidate mismatch'
            if reference is not None:assert np.array_equal(a[:,:2],reference[:,:2]),'per-engine mismatch'
            if candidate_ref is not None:assert np.array_equal(a[:,4:6],candidate_ref[:,4:6]),'per-engine candidates mismatch'
            if args.counters:
                proc=np.zeros(len(a),dtype=np.uint64)
                for word in [32,34,36,38]:proc+=a[:,word].astype(np.uint64)+(a[:,word+1].astype(np.uint64)<<32)
                assert np.array_equal(proc,candidates),'processor candidate conservation'
            log(event='sample',repeat=rep,warmup=rep==0,count=count,seconds=elapsed,per_engine_verified=True,candidates=int(candidates.sum()))
            if rep:times.append(elapsed)
        (args.out/'summary.json').write_text(json.dumps(dict(status='pass',cell=args.cell,counters=args.counters,median_s=statistics.median(times),samples_s=times,l1_actual_bytes=688128),indent=2)+'\n')
    finally:ttnn.close_device(dev);lock.close()
if __name__=='__main__':main()
