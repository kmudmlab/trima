#!/usr/bin/env python3
"""Task 3: rerun the 16 INSIGHTS §1 confirmation pairs with counters compiled out.

Same configs as run_followup.py --selected (levels, page sizes, WeTriC spread 127/tail 0),
same protocol: fresh process per cell, warmup + 3 reps, 3 blocks with seeded order.
'fixture' runs per-engine CPU oracle checks before device timing is trusted.
"""
import argparse,json,random,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parent
INPUTS=Path('/data/dmlab/trima_full_comparison_20260929/artifact/inputs')
SELECTED={'tricore':3,'wetric':2,'steptc':2,'trust-packed':2}
ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--graphs',default='fixture,comlj,orkut,hollywood,stanford')
ap.add_argument('--blocks',type=int,default=3);args=ap.parse_args()
out=R/args.out;out.mkdir(exist_ok=False);records=[]
def save(done):(out/'status.json').write_text(json.dumps(dict(complete=done,records=records),indent=2)+'\n')
for g in args.graphs.split(','):
    fixture=g=='fixture'
    meta=dict(path=str(R.parent.parent/'cpu-validation/clique140.csr'),count=447580) if fixture else json.loads((INPUTS/(g+'.json')).read_text())
    for block in range(1 if fixture else args.blocks):
        jobs=[(m,l) for m in SELECTED for l in (0,SELECTED[m])];random.Random(20261022+block).shuffle(jobs)
        for mode,level in jobs:
            name=f'{g}-{block}-{mode}-opt{level}';dst=out/name;page=256 if mode in ['tricore','wetric'] else 1024
            cmd=[sys.executable,str(R/'nocounters/run_port.py'),'--input',meta['path'],'--out',str(dst),'--expected',str(meta['count']),
                 '--mode',mode,'--opt-level',str(level),'--page-bytes',str(page),'--reps','3']
            if mode=='wetric':cmd+=['--spread','127','--tail','0']
            if fixture:cmd+=['--cpu-check']
            print('START',name,flush=True)
            with dst.with_suffix('.log').open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
            rec=dict(graph=g,block=block,mode=mode,level=level,command=cmd,returncode=rc)
            if not rc:rec['result']=json.loads((dst/'summary.json').read_text())
            records.append(rec);save(False)
            if rc:raise RuntimeError(name)
            print('PASS',name,rec['result']['median_s'],flush=True)
save(True)
