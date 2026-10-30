#!/usr/bin/env python3
"""Task 5 TRUST B0/B2/B3/B4 and existing TriMA on/off, with profile gates."""
import argparse,json,random,statistics,subprocess,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;GAP=HERE.parent;E=HERE.parents[2]
sys.path.insert(0,str(GAP));from run_topdown import BASE
VARIANTS=['B0','trima','notrisc']
ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['fixtures','graph'],required=True);ap.add_argument('--graph',default='fb');ap.add_argument('--out',type=Path,required=True)
args=ap.parse_args();assert args.phase=='graph' and args.graph=='webcc';args.out.mkdir(parents=True,exist_ok=False);records=[]
def save(status):
    (args.out/'status.json').write_text(json.dumps(dict(status=status,records=records),indent=2)+'\n')
def setup(variant):
    if variant.startswith('B'):
        runner=HERE/'code/trust/run_trust_gap.py'
        flags=['--page-bytes','16384' if variant in ['B3','B4'] else '1024','--chunk-kib','262144']
        if variant!='B0':flags+=['--prune','1','--hash-oa','1']
        if variant in ['B3','B4']:flags+=['--direct','1']
        if variant=='B4':flags+=['--lookup-width','4']
    else:
        runner=HERE/'code/trima/run_tuned_dual.py';flags=list(BASE)+['--chunk-kib','262144','--hash-mix','0']
        if variant=='notrisc':flags+=['--no-trisc','1']
    return runner,flags
def run(name,variant,flags,**tags):
    runner,options=setup(variant);dst=args.out/name;cmd=[sys.executable,str(runner),'--out',str(dst),*options,*flags]
    print('START',name,flush=True)
    with (args.out/(name+'.log')).open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
    rec=dict(name=name,variant=variant,returncode=rc,command=cmd,**tags);records.append(rec)
    if rc:save('failed');raise RuntimeError(name)
    rec['summary']=json.loads((dst/'summary.json').read_text());save('running');print('PASS',name,flush=True)
    return dst/('result-1.npy' if variant.startswith('B') else 'raw-1.npy')
def reference(model,variant,path):
    trust=variant.startswith('B');counts=model['counts'];cand=model['trust_candidates' if variant=='B0' else 'pruned_candidates' if trust else 'trima_payload_candidates']
    if not trust:
        counts=[sum(counts[i:i+2]) for i in range(0,len(counts),2)];cand=[sum(cand[i:i+2]) for i in range(0,len(cand),2)]
    a=np.zeros((len(counts),1024),dtype=np.uint32)
    for i,(count,candidate) in enumerate(zip(counts,cand)):
        for word,v in [(0,count),(4 if trust else 26,candidate)]:a[i,word]=v&0xffffffff;a[i,word+1]=v>>32
    np.save(path,a)
def profile(path,variant):
    a=np.load(path);cfg=json.loads((path.parent/'config.json').read_text())
    def vector(w):return [int(r[w])+(int(r[w+1])<<32) for r in a]
    def total(w):return sum(vector(w))
    trust=variant.startswith('B');start=32 if trust else 40
    data=dict(graph=args.graph,variant=variant,input_sha256=cfg['input_sha256'],l1_bytes=cfg['l1_bytes'],page_bytes=cfg['page_bytes'],
        count=total(0),engine_counts=vector(0),logical_owners=len(a),candidates=total(4 if trust else 26),
        engine_candidates=vector(4 if trust else 26),source_rows=total(2),
        candidate_definition='target keys after optional bound' if trust else 'fetched target payload before hybrid/bound probe',
        range_requests=[total(start),total(start+2)],range_bytes=[total(start+4),total(start+6)],read_barriers=total(start+8),
        target_batches=total(10) if trust else sum(int(r[34]) for r in a),cache_misses=[total(6),total(8)] if trust else [0,0])
    denom=data['candidates'];requested=sum(data['range_bytes'])+sum(data['cache_misses'])*cfg['page_bytes']
    data['requested_bytes_per_candidate']=requested/denom if denom else None
    (path.parent/'profile.json').write_text(json.dumps(data,indent=2)+'\n');return data
if args.phase=='fixtures':
    for fixture in ['clique140','long-collision-boundary','random12']:
        meta=json.loads((E/'cpu-validation'/f'{fixture}.json').read_text());model=json.loads((HERE/'cpu-source-models-v1'/f'{fixture}-e220.json').read_text())
        flags=['--input',str(E/'cpu-validation'/f'{fixture}.csr'),'--expected',str(meta['count']),'--reps','1']
        for variant in VARIANTS:
            ref=args.out/f'oracle-{fixture}-{variant}.npy';reference(model,variant,ref)
            extra=['--cpu-check'] if not variant.startswith('B') else []
            run(f'fixture-{fixture}-{variant}',variant,flags+extra+['--profile','--reference',str(ref),'--candidate-reference',str(ref)],phase='fixture')
    fixture='clique140';meta=json.loads((E/'cpu-validation'/f'{fixture}.json').read_text())
    for variant in VARIANTS:
        run(f'fixture-off-{variant}',variant,['--input',str(E/'cpu-validation'/f'{fixture}.csr'),'--expected',str(meta['count']),'--reference',str(args.out/f'oracle-{fixture}-{variant}.npy')]+([] if variant.startswith('B') else ['--cpu-check']),phase='fixture-off')
else:
    graph=next(x for x in json.loads((HERE/'preflight.json').read_text())['graphs'] if x['graph']==args.graph)
    flags=['--input',graph['input_path'],'--expected',str(graph['expected_count']),'--engine-counts',graph['metadata_path']]
    refs={};profiles=[];original={}
    for variant in ['B0','trima']:
        extra=[] if variant.startswith('B') else ['--validated-sha',graph['input_sha256']]
        original[variant]=run(f'original-profile-{variant}',variant,flags+extra+['--profile','--reps','1','--original-kernel'],phase='original-profile')
    for variant in VARIANTS:
        extra=[]
        if variant in original:extra+=['--reference',str(original[variant]),'--candidate-reference',str(original[variant])]
        if variant in ['B2','B3','B4']:extra+=['--reference',str(refs['B0'])]
        if variant in ['B3','B4']:extra+=['--candidate-reference',str(refs['B2'])]
        if variant=='notrisc':extra+=['--reference',str(refs['trima']),'--candidate-reference',str(refs['trima'])]
        if not variant.startswith('B'):extra+=['--validated-sha',graph['input_sha256']]
        refs[variant]=run(f'profile-{variant}',variant,flags+extra+['--profile','--reps','1'],phase='profile')
        profiles.append(profile(refs[variant],variant))
    (args.out/'profiles.json').write_text(json.dumps(profiles,indent=2)+'\n')
    for block in range(3):
        variants=list(VARIANTS);random.Random(20261022+block).shuffle(variants)
        for variant in variants:
            extra=[] if variant.startswith('B') else ['--validated-sha',graph['input_sha256']]
            run(f'block{block}-{variant}',variant,flags+extra+['--reps','3','--reference',str(refs[variant])],phase='timing',block=block)
    med={v:statistics.median(r['summary']['median_s'] for r in records if r.get('phase')=='timing' and r['variant']==v) for v in VARIANTS}
    ratios={f'{a}/{b}':med[a]/med[b] for a,b in [('notrisc','trima')]}
    (args.out/'comparison.private.json').write_text(json.dumps(dict(graph=args.graph,seconds=med,ratios=ratios),indent=2)+'\n')
    (args.out/'counterexamples.json').write_text(json.dumps({k:v for k,v in ratios.items() if v<1},indent=2)+'\n')
save('complete_with_time_limits')
