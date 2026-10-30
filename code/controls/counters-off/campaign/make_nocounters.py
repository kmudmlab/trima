#!/usr/bin/env python3
"""Build gap/nocounters/: a copy of bounded/ whose diagnostic counters compile to no-ops.

Only Counters.{jobs,candidates,probes} and IO page-miss tallies are disabled. Counters.count
(the triangle total) and error remain real. bounded/ itself is never modified.
"""
import hashlib,json,shutil
from pathlib import Path
R=Path(__file__).resolve().parent;SRC=R.parent/'bounded';DST=R/'nocounters'
DST.mkdir(exist_ok=False)
for name in ['algorithms.hpp','optimized.hpp','port_kernel.cpp','prepare.cpp','reduce.py','run_port.py','prepare-0','prepare-2','prepare-3']:
    shutil.copy2(SRC/name,DST/name)
def patch(name,old,new,times=1):
    p=DST/name;t=p.read_text();assert t.count(old)==times,(name,old,t.count(old));p.write_text(t.replace(old,new))
patch('algorithms.hpp','''struct Counters {
    uint64_t count=0, jobs=0, candidates=0, probes=0;
    uint32_t error=0;
};''','''// gap/nocounters: diagnostic tallies compile to no-ops; count and error stay real.
struct Nop {
    Nop& operator++(){return *this;} Nop operator++(int){return *this;}
    template<class T> Nop& operator+=(T){return *this;}
    operator uint64_t() const {return 0;}
};
struct Counters {
    uint64_t count=0; Nop jobs, candidates, probes;
    uint32_t error=0;
};''')
patch('port_kernel.cpp','noc_async_read_barrier();tags[at]=pg;++reads[which];','noc_async_read_barrier();tags[at]=pg;')
patch('run_port.py',"limitations='Static two-DM execution. Counters enabled for all variants;","counters='off (diagnostic tallies compiled to no-ops; count/error real)',limitations='Static two-DM execution. Counters DISABLED in this copy;")
patch('run_port.py',"stage='optimization_ablation_20261022'","stage='gap_nocounters_20261022'",times=2)
# Share the campaign lock held by gap/run_topdown.py (optimization_20261022/hardware.lock).
patch('run_port.py',"lock=(HERE/'hardware.lock').open('a')","lock=(HERE.parent.parent/'hardware.lock').open('a')")
manifest={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DST.iterdir()) if p.is_file()}
manifest.update({f'source:bounded/{k}':hashlib.sha256((SRC/k).read_bytes()).hexdigest() for k in ['algorithms.hpp','port_kernel.cpp','run_port.py']})
(R/'nocounters-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=1))
