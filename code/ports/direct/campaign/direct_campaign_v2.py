#!/usr/bin/env python3
"""Task 5 direct families, one graph/phase per invocation to alternate device ownership."""
import argparse,json,random,statistics,subprocess,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;GAP=HERE.parent;E=GAP.parents[1]
RUN=HERE/'code/direct/run_port.py'
sys.path.insert(0,str(GAP));from run_direct_campaign import ALGOS
CHOSEN={'steptc':['base','D1-direct','D2-oa','D3-oa-w4'],'wetric':['base','D1-direct','D5-bl4'],'tricore':['base','D1-direct']}
ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['fixtures','graph'],required=True)
ap.add_argument('--graph',default='fb');ap.add_argument('--out',type=Path,required=True)
args=ap.parse_args();assert args.phase=='graph' and args.graph=='webcc';args.out.mkdir(parents=True,exist_ok=False);records=[]
def save(status):
    (args.out/'status.json').write_text(json.dumps(dict(status=status,records=records),indent=2)+'\n')
def run(name,flags,**tags):
    dst=args.out/name;cmd=[sys.executable,str(RUN),'--out',str(dst),*flags]
    print('START',name,flush=True)
    with (args.out/(name+'.log')).open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
    rec=dict(name=name,returncode=rc,command=cmd,**tags);records.append(rec)
    if rc:save('failed');raise RuntimeError(name)
    rec['summary']=json.loads((dst/'summary.json').read_text());save('running');print('PASS',name,flush=True)
    # Reproducible successful auxiliary input is represented by SHA and preparation command.
    # Failed cells are never cleaned; keep all output vectors, manifests and source snapshots.
    if (dst/'aux.bin').stat().st_size>64*1024*1024:
        (dst/'aux.bin').unlink();rec['aux_removed_after_pass']=True;save('running')
    return dst
def profile(dst,family,variant):
    a=np.load(dst/'result-1.npy');cfg=json.loads((dst/'config.json').read_text())
    def vec(word):return [int(r[word])+(int(r[word+1])<<32) for r in a]
    def total(word):return sum(vec(word))
    counters=dict(count=total(0),engine_counts=vec(0),jobs=total(2),candidates=total(4),engine_candidates=vec(4),probes=total(6),
        row_pages=total(8),col_pages=total(10),aux_pages=total(12),range_requests_row_col_aux=[total(w) for w in [32,34,36]],
        range_bytes_row_col_aux=[total(w) for w in [38,40,42]],wait_calls=total(44),target_batches=total(46),metadata_batches=total(48))
    denom=counters['candidates'];miss=sum(counters[k] for k in ['row_pages','col_pages','aux_pages'])
    requested=miss*cfg['page_bytes']+sum(counters['range_bytes_row_col_aux'])
    record=dict(graph=args.graph,family=family,variant=variant,input_sha256=cfg['source_sha256'],aux_sha256=cfg['aux_sha256'],
        l1_bytes=cfg['l1_bytes'],page_bytes=cfg['page_bytes'],counters=counters,
        derived=dict(cache_misses_per_candidate=miss/denom if denom else None,requested_bytes_per_candidate=requested/denom if denom else None,
                     candidates_per_target_batch=denom/counters['target_batches'] if counters['target_batches'] else None),
        unavailable=['high_degree_candidates','hash_rows','hash_keys','hash_insert_collisions','bucket_entries_and_nonempty_buckets'],
        definition='StepTC: target-row keys; WeTriC: oriented wedges; TriCore: selected shorter-row keys. Probe semantics remain implementation-specific.')
    (dst/'profile.json').write_text(json.dumps(record,indent=2)+'\n');return record
if args.phase=='fixtures':
    for fx in ['clique140','long-collision-boundary','random12']:
        meta=json.loads((E/'cpu-validation'/f'{fx}.json').read_text())
        flags=['--input',str(E/'cpu-validation'/f'{fx}.csr'),'--expected',str(meta['count']),'--cpu-check','--counters','1','--reps','1']
        for family,names in CHOSEN.items():
            ref=None
            for name in names:
                extra=[] if ref is None else ['--reference',str(ref),'--candidate-reference',str(ref)]
                dst=run(f'{fx}-{family}-{name}',flags+ALGOS[family][name]+extra,phase='fixture',family=family,variant=name)
                if ref is None:ref=dst/'result-1.npy'
else:
    graph=next(g for g in json.loads((HERE/'preflight.json').read_text())['graphs'] if g['graph']==args.graph)
    flags=['--input',graph['input_path'],'--expected',str(graph['expected_count']),'--validated-sha',graph['input_sha256']]
    references={};profiles=[]
    prior=HERE/'webcc-direct-continue-v1'
    for variant in CHOSEN['steptc']:
        if variant!='D3-oa-w4':
            profiles.append(json.loads((prior/f'profile-steptc-{variant}'/'profile.json').read_text()))
    references['steptc']=prior/'profile-steptc-base/result-1.npy'
    CHOSEN['steptc']=['base','D1-direct']
    for family,names in CHOSEN.items():
        for name in names:
            if family=='steptc':continue
            ref=references.get(family);extra=[] if ref is None else ['--reference',str(ref),'--candidate-reference',str(ref)]
            dst=run(f'profile-{family}-{name}',flags+ALGOS[family][name]+['--counters','1','--reps','1']+extra,phase='profile',family=family,variant=name)
            profiles.append(profile(dst,family,name))
            # Add only absent profile aliases for the analyst's existing read-only waiter.
            alias=prior/dst.name
            assert not alias.exists() and not alias.is_symlink(),alias
            alias.symlink_to(dst.resolve(),target_is_directory=True)
            if ref is None:references[family]=dst/'result-1.npy'
    (args.out/'profiles.json').write_text(json.dumps(profiles,indent=2)+'\n')
    for block in range(3):
        jobs=[(f,v) for f,vs in CHOSEN.items() for v in vs];random.Random(20261022+block).shuffle(jobs)
        for family,name in jobs:
            run(f'block{block}-{family}-{name}',flags+ALGOS[family][name]+['--counters','0','--reps','3','--reference',str(references[family])],phase='timing',family=family,variant=name,block=block)
    med={f'{f}/{v}':statistics.median(r['summary']['median_s'] for r in records if r['phase']=='timing' and r['family']==f and r['variant']==v) for f,vs in CHOSEN.items() for v in vs}
    effects={f'{f}:base/{v}':med[f'{f}/base']/med[f'{f}/{v}'] for f,vs in CHOSEN.items() for v in vs if v!='base'}
    (args.out/'comparison.private.json').write_text(json.dumps(dict(graph=args.graph,seconds=med,ratios=effects),indent=2)+'\n')
    counterexamples={k:v for k,v in effects.items() if v<1}
    (args.out/'counterexamples.json').write_text(json.dumps(counterexamples,indent=2)+'\n')
save('complete_with_time_limits')
