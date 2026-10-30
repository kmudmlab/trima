#!/usr/bin/env python3
"""Exploratory TT cache allocation, respecting the same per-core SRAM ceiling."""
import json,random,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parent;out=R/'capacity';out.mkdir(exist_ok=False);records=[]
pages={'tricore':256,'wetric':256,'steptc':1024}
protocol=dict(pages=pages,col_cache_kib=[64,512],cores=110,engines=2,quota_bytes=1392*1024,
              selection='Page sizes chosen on the preceding comlj exploratory ablation. This is tuning evidence, not held-out statistical confirmation.',
              repetitions='One fresh process with one warmup and three measured epochs per cell.')
(out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
def run(name,mode,inp,expected,extra,cpu=False):
    dst=out/name;cmd=[sys.executable,str(R/'run_port.py'),'--mode',mode,'--input',str(inp),'--expected',str(expected),'--out',str(dst),'--reps','3']+extra
    if cpu:cmd+=['--cpu-check']
    print('START',name,flush=True)
    with dst.with_suffix('.log').open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
    r=dict(name=name,mode=mode,command=cmd,returncode=rc)
    if not rc:r['result']=json.loads((dst/'summary.json').read_text())
    records.append(r);(out/'status.json').write_text(json.dumps(dict(complete=False,records=records),indent=2)+'\n')
    if rc:raise RuntimeError(name)
    print('PASS',name,r['result']['median_s'],flush=True)
for mode in [*pages,'btc-scalar']:
    extra=['--aux-cache-kib','512'] if mode=='btc-scalar' else ['--col-cache-kib','512','--page-bytes',str(pages[mode])]
    run('fixture-'+mode,mode,R/'cpu-validation/clique140.csr',447580,extra,True)
for graph in ['comlj','orkut']:
    m=json.loads((Path('/data/dmlab/trima_full_comparison_20260929/artifact/inputs')/(graph+'.json')).read_text())
    jobs=[(mode,kib) for mode in pages for kib in [64,512]];random.Random(20261021).shuffle(jobs)
    for mode,kib in jobs:run(f'{graph}-{mode}-{kib}',mode,m['path'],m['count'],['--col-cache-kib',str(kib),'--page-bytes',str(pages[mode])])
    if graph=='comlj':run('comlj-btc-scalar-512','btc-scalar',m['path'],m['count'],['--aux-cache-kib','512'])
(out/'status.json').write_text(json.dumps(dict(complete=True,records=records),indent=2)+'\n')
