#!/usr/bin/env python3
"""Summarize direct-v1 (step D + task 5): median-of-block-medians, ratios to baseline, per-engine
equality of every timing cell with its block baseline (same ownership), profile candidate checks."""
import collections,json,statistics,sys
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent;out=R/(sys.argv[1] if len(sys.argv)>1 else 'direct-v1')
S=json.loads((out/'status.json').read_text());recs=S['records']
def engine_counts(name):
    a=np.load(out/name/'result-1.npy');return (a[:,0].astype(np.uint64)+(a[:,1].astype(np.uint64)<<32)).tolist()
res=dict(complete=S['complete'],cells=len(recs),failures=[r['name'] for r in recs if r['returncode']],
         fixtures=sum(r['phase']=='fixture' for r in recs),profile=[],timing={},grid={},per_engine_mismatch=[])
for r in recs:
    if r['phase']=='profile':res['profile'].append(dict(name=r['name'],candidates=r.get('candidates'),matches=r.get('matches_baseline')))
t=collections.defaultdict(list);l1={}
for r in recs:
    if r['phase'] in ('timing','grid'):
        t[(r['phase'],r['graph'],r['algo'],r['variant'])].append(r['result']['median_s']);l1[(r['algo'],r['variant'])]=r['result']['l1_bytes']//1024
# per-engine equality vs the same block's baseline (timing phase)
for r in recs:
    if r['phase']=='timing' and r['variant']!='base':
        base=f"{r['graph']}-{r['block']}-{r['algo']}-base"
        if engine_counts(r['name'])!=engine_counts(base):res['per_engine_mismatch'].append(r['name'])
for (ph,g,a,v),x in sorted(t.items()):
    m=statistics.median(x);key=f'{g}/{a}/{v}'
    entry=dict(median_s=m,blocks=len(x),spread=(max(x)-min(x))/m,l1_kib=l1[(a,v)])
    if ph=='timing':
        b=statistics.median(t[('timing',g,a,'base')]);entry['speedup_vs_base']=b/m;res['timing'][key]=entry
    else:
        b=statistics.median(t[('grid',g,'grid','c1-h0-b0')]);entry['speedup_vs_c1h0b0']=b/m;res['grid'][key]=entry
print(json.dumps(res,indent=1))
