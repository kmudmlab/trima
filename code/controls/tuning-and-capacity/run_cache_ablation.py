#!/usr/bin/env python3
"""Fixed capacity, page-size intervention across three distinct algorithms."""
import json,random,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parent
out=R/'cache-ablation';out.mkdir(exist_ok=False)
meta=json.loads(Path('/data/dmlab/trima_full_comparison_20260929/artifact/inputs/comlj.json').read_text())
protocol=dict(graph='comlj',blocks=3,pages=[256,1024,4096],modes=['tricore','wetric','steptc'],
              fixed_row_cache_bytes=16384,fixed_col_cache_bytes=65536,fixed_aux_cache_bytes=16384,cores=110,engines=2,
              caveat='Cache data capacity is fixed; tag bytes vary with page count and are reported. Algorithm counters enabled for every cell. Exploratory ablation, not a held-out optimum.')
(out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n');records=[]
for block in range(3):
    jobs=[(m,p) for m in protocol['modes'] for p in protocol['pages']];random.Random(20261021+block).shuffle(jobs)
    for mode,page in jobs:
        dst=out/f'{block}-{mode}-{page}'
        cmd=[sys.executable,str(R/'run_port.py'),'--input',meta['path'],'--expected',str(meta['count']),'--mode',mode,'--out',str(dst),'--page-bytes',str(page),'--reps','1']
        print('START',dst.name,flush=True)
        with dst.with_suffix('.log').open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
        r=dict(block=block,mode=mode,page=page,command=cmd,returncode=rc)
        if not rc:r['result']=json.loads((dst/'summary.json').read_text())
        records.append(r);(out/'status.json').write_text(json.dumps(dict(complete=False,records=records),indent=2)+'\n')
        if rc:raise RuntimeError(dst.name)
        print('PASS',dst.name,r['result']['median_s'],flush=True)
(out/'status.json').write_text(json.dumps(dict(complete=True,records=records),indent=2)+'\n')
