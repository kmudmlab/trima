#!/usr/bin/env python3
"""Serial Task 4 phases. Profiles gate timing; every cell retains per-engine vectors."""
import argparse,json,random,statistics,subprocess,sys
from pathlib import Path
from decode_profile import extract
HERE=Path(__file__).resolve().parent;GAP=HERE.parent;E=HERE.parents[2]
RUN=HERE/'run_step.py';ANCHOR=GAP/'suite-v1/code/direct/run_port.py'
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
ap.add_argument('--phase',choices=['fixtures','graph'],required=True);ap.add_argument('--graph',default='stanford')
args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=False);records=[]
def save(status):
    (args.out/'status.json').write_text(json.dumps(dict(status=status,records=records),indent=2)+'\n')
def run(name,runner,flags,**tags):
    dst=args.out/name;cmd=[sys.executable,str(runner),'--out',str(dst),*flags]
    print('START',name,flush=True)
    with (args.out/(name+'.log')).open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
    rec=dict(name=name,command=cmd,returncode=rc,**tags);records.append(rec)
    if rc:save('failed');raise RuntimeError(name)
    rec['summary']=json.loads((dst/'summary.json').read_text());save('running');print('PASS',name,flush=True)
    return dst
def anchor_flags(name):
    return ['--mode','steptc' if name=='opt2' else 'steptc-direct','--opt-level','2']+([] if name=='opt2' else ['--hash-oa','1','--lookup-width','4'])
if args.phase=='fixtures':
    for fx in ['clique140','long-collision-boundary','random12']:
        meta=json.loads((E/'cpu-validation'/f'{fx}.json').read_text())
        flags=['--input',str(E/'cpu-validation'/f'{fx}.csr'),'--expected',str(meta['count']),'--cpu-check','--reps','3']
        for cores in [1,110]:
            for cell in ['C0','C1','D0','D1']:
                run(f'{fx}-{cores}-{cell}',RUN,flags+['--cores',str(cores),'--cell',cell,'--counters','1','--stress','1000'],phase='fixture')
    for cell in ['C0','C1','D0','D1']:
        meta=json.loads((E/'cpu-validation/clique140.json').read_text())
        run(f'off-clique140-{cell}',RUN,['--input',str(E/'cpu-validation/clique140.csr'),'--expected',str(meta['count']),'--cpu-check','--cell',cell,'--counters','0'],phase='fixture-off')
else:
    graph=next(x for x in json.loads((GAP/'suite-v1/preflight.json').read_text())['graphs'] if x['graph']==args.graph)
    flags=['--input',graph['input_path'],'--expected',str(graph['expected_count']),'--validated-sha',graph['input_sha256']]
    ref=run('profile-D3',ANCHOR,flags+anchor_flags('D3')+['--counters','1','--reps','1'],phase='profile')/'result-1.npy'
    for cell in ['opt2','C0','C1','D0','D1']:
        runner=ANCHOR if cell=='opt2' else RUN
        options=anchor_flags(cell) if cell=='opt2' else ['--cell',cell]
        dst=run(f'profile-{cell}',runner,flags+options+['--counters','1','--reps','1','--reference',str(ref),'--candidate-reference',str(ref)],phase='profile')
        if runner==RUN:
            (dst/'profile.json').write_text(json.dumps(extract(dst),indent=2,ensure_ascii=False)+'\n')
    for block in range(3):
        cells=['opt2','D3','C0','C1','D0','D1'];random.Random(20261022+block).shuffle(cells)
        for cell in cells:
            runner=ANCHOR if cell in ['opt2','D3'] else RUN
            options=anchor_flags(cell) if runner==ANCHOR else ['--cell',cell]
            run(f'block{block}-{cell}',runner,flags+options+['--counters','0','--reps','3','--reference',str(ref)],phase='timing',cell=cell,block=block)
    med={c:statistics.median(r['summary']['median_s'] for r in records if r.get('cell')==c) for c in ['opt2','D3','C0','C1','D0','D1']}
    effects={f'{a}/{b}':med[a]/med[b] for a,b in [('C0','C1'),('D0','D1'),('C0','D0'),('C1','D1'),('opt2','C0'),('D3','D0')]}
    (args.out/'comparison.json').write_text(json.dumps(dict(graph=args.graph,seconds=med,ratios=effects),indent=2)+'\n')
    counterexamples={k:v for k,v in effects.items() if k in ['C0/D0','C1/D1'] and v<1}
    (args.out/'counterexamples.json').write_text(json.dumps(counterexamples,indent=2)+'\n')
save('complete')
