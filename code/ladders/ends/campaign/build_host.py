"""Actual TRUST producer + synchronous CPU NoC/worker shim; not a memory-order proof."""
from pathlib import Path
import sys,subprocess,json,traceback,shutil
P=Path(__file__).resolve().parent;C=P/'code';io='--io-only' in sys.argv
s=(C/'step_reader.cpp').read_text().replace('#include "api/dataflow/dataflow_api.h"','')
s=s.replace('// SHARED',(C/'step_shared.hpp').read_text()).replace('// METADATA_PLAN',(C/'metadata.hpp').read_text())
s=s.replace('void kernel_main()','void replay_kernel()').replace('asm volatile("fence" ::: "memory");','').replace('2*cores','cpu_engines')
s=s.replace('uint32_t base=get_write_ptr','uintptr_t base=get_write_ptr')
for a,b in [('(uint32_t)tail','(uintptr_t)tail'),('(uint32_t)packed','(uintptr_t)packed'),('(uint32_t)dst','(uintptr_t)dst'),('(uint32_t)(cache','(uintptr_t)(cache'),('(uint32_t)result','(uintptr_t)result'),('uint32_t(dst)','uintptr_t(dst)'),('(uint32_t)(packed','(uintptr_t)(packed')]:s=s.replace(a,b)
a=s.index('    uint32_t spins=0;');b=s.index('    auto fetch=',a)
s=s[:a]+'    auto wait_ack=[&](uint32_t,bool)->bool { return !error; };\n'+s[b:]
a=s.index('    spins=0;',s.index('sync[EOF_SEQ]'));b=s.index('    uint64_t total=',a);s=s[:a]+s[b:]
s=s.replace('// ACCESSORS','auto output=0;')
# Run the real consumer probe over its exclusive job subset at each publish.
needle='sync[off]=next; seq=next; last_sequence[ctx]=seq;'
assert s.count(needle)==2
injection='''
#if TRISC_ON
                for(uint32_t worker=0;worker<3;++worker) {
                    ProbeStats worker_stats; uint64_t worker_count=0;
                    for(uint32_t j=worker;j<batch;j+=4) {
                        worker_count+=probe(jobs[j],src,hash,target+jobs[j].target_offset,worker_stats);
                    }
                    const uint32_t at=WORKER+worker*32;
                    put64(sync,at,get64(sync,at)+worker_count);
                    put64(sync,at+2,get64(sync,at+2)+worker_stats.candidates);
                    put64(sync,at+4,get64(sync,at+4)+worker_stats.probes);
                    put64(sync,at+22,get64(sync,at+22)+worker_stats.identity1);
                    put64(sync,at+24,get64(sync,at+24)+worker_stats.identity2);
                }
#endif
'''
s=s.replace(needle,needle+injection)
if io:
 a=s.index('inline uint32_t probe(');b=s.index('\n// Complete rows only.',a)
 s=s[:a]+'''inline uint32_t probe(const Job& job,const uint32_t* src,const uint32_t*,const uint32_t* target,ProbeStats& stats) {
    stats.candidates+=job.length;
    const uint64_t u=uint64_t(job.source_u)+1,v=uint64_t(src[job.ordinal])+1;
    (void)target; const uint64_t first=arrays[0][src[job.ordinal]],last=first+job.length;
    uint64_t sum=key_sum[last]-key_sum[first],square=key_square[last]-key_square[first];
    stats.identity1+=uint64_t(job.length)*(u*0x9e3779b1ull+v*0x85ebca6bull)+sum;
    stats.identity2+=uint64_t(job.length)*u*v+square;
    return 0;
}
'''+s[b:]
 s=s.replace('build_hash(loaded,c.degree,hb,ub,c.nused);','c.nused=0;')
(C/'host_kernel.hpp').write_text(s)
(C/('host_kernel_io.hpp' if io else 'host_kernel_semantic.hpp')).write_text(s)
out=P/('host-bin-io' if io else 'host-bin');out.mkdir(exist_ok=True)
records=[]
try:
 for v in json.loads((P/'VARIANTS.json').read_text()):
  cmd=['c++','-O2','-std=c++17','-Wall','-Wextra','-Werror','-Wno-unused-variable','-Wno-unused-parameter',
       '-DFAMILY=4',f'-DDIRECT={int(v["supply"]=="range")}',f'-DTAIL_ON={v["tail"]}',f'-DTRISC_ON={v["trisc"]}',f'-DSOURCE_CONTEXTS={v["contexts"]}',
       '-DREPLAY_IO_ONLY=1' if io else '-DHOST_TRACE=1',str(C/'host.cpp'),'-o',str(out/v['name'])]
  r=subprocess.run(cmd,capture_output=True,text=True);(out/(v['name']+'.build.log')).write_text(r.stdout+r.stderr)
  if r.returncode:raise RuntimeError(('compiler',v['name'],r.stderr))
  records.append(v['name'])
 (out/'COMPLETE.json').write_text(json.dumps(dict(status='pass',binaries=records),indent=2)+'\n')
except BaseException as e:
 (out/'BUILD_FAILURE.json').write_text(json.dumps(dict(error=repr(e),records=records,traceback=traceback.format_exc()),indent=2)+'\n');raise
