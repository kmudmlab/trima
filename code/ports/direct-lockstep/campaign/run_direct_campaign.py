#!/usr/bin/env python3
"""Step D (+ task 5): TRUST step-B execution changes applied to StepTC, WeTriC and TriCore-COO.

Phase 1 fixtures on device with per-engine CPU oracle. Phase 2 PROFILE (counters on): each direct
variant must equal its baseline's candidate total and per-engine counts on the same graph.
Phase 3 timing (counters off), fresh process per cell, warmup + 3 reps, 3 seeded blocks; baselines
run inside the same blocks. Task 5 grid: TriCore-COO opt2 + {chunk32, held, bound} on/off.
Any failure stops the campaign.
"""
import argparse,itertools,json,random,subprocess,sys
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent;E=R.parent.parent
INPUTS=Path('/data/dmlab/trima_full_comparison_20260929/artifact/inputs')
RUN=R/'direct/run_port.py'
def v(mode,level,page,**k):
    f=['--mode',mode,'--opt-level',str(level),'--page-bytes',str(page)]
    for a,b in k.items():f+=['--'+a.replace('_','-'),str(b)]
    if mode.startswith('wetric'):f+=['--spread','127','--tail','0']
    return f
ALGOS={
 'steptc':{'base':v('steptc',2,1024),
           'D1-direct':v('steptc-direct',2,1024),
           'D2-oa':v('steptc-direct',2,1024,hash_oa=1),
           'D3-oa-w4':v('steptc-direct',2,1024,hash_oa=1,lookup_width=4),
           'D4-bl1':v('steptc-direct',2,1024,hash_oa=1,branchless=1),
           'D5-bl4':v('steptc-direct',2,1024,hash_oa=1,branchless=1,lookup_width=4)},
 'wetric':{'base':v('wetric',2,256),
           'D1-direct':v('wetric-direct',2,256),
           'D4-bl1':v('wetric-direct',2,256,branchless=1),
           'D5-bl4':v('wetric-direct',2,256,branchless=1,lookup_width=4)},
 'tricore':{'base':v('tricore-coo',3,256),
            'D1-direct':v('tricore-coo-direct',2,256),
            'D4-bl1':v('tricore-coo-direct',2,256,branchless=1),
            'D5-bl4':v('tricore-coo-direct',2,256,branchless=1,lookup_width=4)},
}
GRID={f'c{c}-h{h}-b{b}':v('tricore-coo-grid',2,256,tc_chunk=c,tc_held=h,tc_bound=b) for c,h,b in itertools.product([1,32],[0,1],[0,1])}
FIXTURES=['clique40','clique140','long-collision-boundary','random3','random12']
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--graphs',default='comlj,orkut,hollywood,stanford')
    ap.add_argument('--grid-graphs',default='comlj,orkut');ap.add_argument('--blocks',type=int,default=3);ap.add_argument('--phases',default='1,2,3,4')
    args=ap.parse_args();out=R/args.out;out.mkdir(exist_ok=False);records=[];phases=set(args.phases.split(','))
    def save(done):(out/'status.json').write_text(json.dumps(dict(complete=done,records=records),indent=2)+'\n')
    def run(name,flags,phase,**info):
        dst=out/name;cmd=[sys.executable,str(RUN),'--out',str(dst)]+flags;print('START',name,flush=True)
        with dst.with_suffix('.log').open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
        rec=dict(name=name,phase=phase,command=cmd,returncode=rc,**info)
        if not rc:rec['result']=json.loads((dst/'summary.json').read_text())
        records.append(rec);save(False)
        if rc:raise RuntimeError(name)
        print('PASS',name,rec['result']['median_s'],flush=True);return dst,rec
    def graph(g):m=json.loads((INPUTS/(g+'.json')).read_text());return ['--input',m['path'],'--expected',str(m['count'])]
    def fixture(fx):m=json.loads((E/'cpu-validation'/(fx+'.json')).read_text());return ['--input',str(E/'cpu-validation'/(fx+'.csr')),'--expected',str(m['count']),'--cpu-check']
    if '1' in phases:
        for fx in FIXTURES:
            for a,vs in ALGOS.items():
                for name,fl in vs.items():run(f'fixture-{fx}-{a}-{name}',fixture(fx)+['--reps','1']+fl,'fixture',graph=fx,algo=a,variant=name)
            if fx in ['clique140','long-collision-boundary']:
                for name,fl in GRID.items():run(f'fixture-{fx}-grid-{name}',fixture(fx)+['--reps','1']+fl,'fixture',graph=fx,algo='grid',variant=name)
    if '2' in phases:
        for g in ['comlj','orkut']:
            for a,vs in ALGOS.items():
                ref=None
                for name,fl in vs.items():
                    dst,rec=run(f'{g}-profile-{a}-{name}',graph(g)+['--reps','1','--counters','1']+fl,'profile',graph=g,algo=a,variant=name)
                    res=np.load(dst/'result-1.npy');counts=(res[:,0].astype(np.uint64)+(res[:,1].astype(np.uint64)<<32)).tolist()
                    cand=rec['result']['metrics'][2]
                    if ref is None:ref=(cand,counts)
                    else:
                        assert cand==ref[0],(name,'candidates',cand,ref[0])
                        assert counts==ref[1],(name,'per-engine counts differ from baseline')
                    rec.update(candidates=cand,matches_baseline=True);save(False)
    if '3' in phases:
        for g in args.graphs.split(','):
            for block in range(args.blocks):
                jobs=[(a,name) for a,vs in ALGOS.items() for name in vs];random.Random(20261022+block).shuffle(jobs)
                for a,name in jobs:run(f'{g}-{block}-{a}-{name}',graph(g)+['--reps','3']+ALGOS[a][name],'timing',graph=g,algo=a,variant=name,block=block)
    if '4' in phases:
        for g in args.grid_graphs.split(','):
            for block in range(args.blocks):
                names=list(GRID);random.Random(20261022+block).shuffle(names)
                for name in names:run(f'{g}-{block}-grid-{name}',graph(g)+['--reps','3']+GRID[name],'grid',graph=g,algo='grid',variant=name,block=block)
    save(True)
if __name__=='__main__':main()
