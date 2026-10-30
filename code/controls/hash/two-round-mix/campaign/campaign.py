#!/usr/bin/env python3
"""hash 섞기 통제 대조. 정확성 gate 뒤 같은 block에서 0/1을 비교한다."""
import argparse,json,os,random,statistics,subprocess,sys,time
from pathlib import Path
import numpy as np
H=Path(__file__).resolve().parent;G=H.parent;S=G/'suite-v1';E=H.parents[2]
sys.path.insert(0,str(G));from run_direct_campaign import ALGOS
from run_topdown import BASE
ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['fixtures','ports','trima'],required=True)
ap.add_argument('--graph',default='fb');ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
if a.phase=='trima':
 sys.path.insert(0,str(H.parent/'multiply-shift'))
 from queue_entry import trima
 if trima(a.graph,a.out):sys.exit(0)
a.out.mkdir(parents=True,exist_ok=False);records=[]
variants={}
for name in ['D1-direct','D2-oa','D3-oa-w4']:
 variants['steptc-'+name]=dict(family='steptc',variant=name,mix=0,flags=ALGOS['steptc'][name]+['--hash-mix','0'])
 if name!='D1-direct':variants['steptc-'+name+'-mix']=dict(family='steptc',variant=name,mix=1,flags=ALGOS['steptc'][name]+['--hash-mix','1'])
for name in ['B2','B3','B4']:
 flags=['--page-bytes','1024' if name=='B2' else '16384','--chunk-kib','262144','--prune','1','--hash-oa','1']
 if name!='B2':flags+=['--direct','1']
 if name=='B4':flags+=['--lookup-width','4']
 for mix in [0,1]:variants['trust-'+name+('-mix' if mix else '')]=dict(family='trust',variant=name,mix=mix,flags=flags+['--hash-mix',str(mix)])
for mix in [0,1]:
 # BASE contains the historic explicit zero; the last argparse value is deliberate.
 variants[f'trima-mix{mix}']=dict(family='trima',variant='trima',mix=mix,flags=list(BASE)+['--chunk-kib','262144','--hash-mix',str(mix)])
def save(status,active=None):
 (a.out/'status.json').write_text(json.dumps(dict(status=status,pid=os.getpid(),phase=a.phase,graph=a.graph,active=active,records=records),indent=2)+'\n')
def run(name,key,input_path,expected,profile,reference,metadata=None):
 v=variants[key];family=v['family'];dst=a.out/name
 runner=H/'code'/('direct/run_port.py' if family=='steptc' else 'trust/run_trust_gap.py' if family=='trust' else 'trima/run_tuned_dual.py')
 cmd=[sys.executable,str(runner),'--input',str(input_path),'--expected',str(expected),'--out',str(dst),*v['flags'],'--reps','1' if profile or a.phase=='fixtures' else '3','--reference',str(reference)]
 if family=='steptc':cmd+=['--counters',str(int(profile))]
 elif profile:cmd+=['--profile']
 if profile:cmd+=['--candidate-reference',str(reference)]
 if metadata:
  if family!='steptc':cmd+=['--engine-counts',metadata['metadata_path']]
  if family!='trust':cmd+=['--validated-sha',metadata['input_sha256']]
 elif family!='trust':cmd+=['--cpu-check']
 print('START',name,flush=True)
 with (a.out/(name+'.log')).open('x') as log:
  child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
  save('running',dict(name=name,pid=child.pid,command=cmd,started_unix=time.time()));rc=child.wait()
 r=dict(name=name,key=key,phase='profile' if profile else 'timing',returncode=rc,command=cmd);records.append(r)
 if rc:save('failed');raise RuntimeError(name)
 r['summary']=json.loads((dst/'summary.json').read_text());save('running')
 result=dst/('raw-1.npy' if family=='trima' else 'result-1.npy')
 if profile:
  raw=np.load(result);cfg=json.loads((dst/'config.json').read_text())
  def vec(w):return [int(row[w])+(int(row[w+1])<<32) for row in raw]
  pword=6 if family=='steptc' else 42 if family=='trust' else 50
  cword=50 if family=='steptc' else 44 if family=='trust' else 52
  candidate_word=26 if family=='trima' else 4
  payload=dict(graph=a.graph,key=key,family=family,hash_mix=v['mix'],count=sum(vec(0)),engine_counts=vec(0),
               candidates=sum(vec(candidate_word)),engine_candidates=vec(candidate_word),probe_steps=sum(vec(pword)),
               hash_insert_collisions=sum(vec(cword)),l1_bytes=cfg['l1_bytes'],
               probe_definition='StepTC: existing low-row binary steps plus OA nonmatching occupied-slot steps; TRUST/TriMA: hash nonmatching occupied-slot steps only. Initial/terminal loads excluded.',
               profile_cell=str(dst),input_sha256=cfg.get('source_sha256',cfg.get('input_sha256')))
  (dst/'profile.json').write_text(json.dumps(payload,indent=2)+'\n')
 aux=dst/'aux.bin'
 if aux.exists() and aux.stat().st_size>64*1024*1024:aux.unlink();r['aux_removed_after_pass']=True
 save('running');print('PASS',name,flush=True);return result
if a.phase=='fixtures':
 for fx in ['clique140','long-collision-boundary','random12']:
  meta=json.loads((E/'cpu-validation'/f'{fx}.json').read_text())
  refs={}
  for key,v in variants.items():
   if v['family']=='steptc':ref=S/'device-fixtures-v1'/f'{fx}-steptc-base/result-1.npy'
   else:ref=S/'source-device-fixtures-v2'/f'oracle-{fx}-{v["variant"]}.npy'
   refs[key]=run(f'{fx}-{key}',key,E/'cpu-validation'/f'{fx}.csr',meta['count'],True,ref)
  if fx=='clique140':
   for key in variants:run('off-'+key,key,E/'cpu-validation'/f'{fx}.csr',meta['count'],False,refs[key])
else:
 g=next(x for x in json.loads((S/'preflight.json').read_text())['graphs'] if x['graph']==a.graph)
 selected=[key for key,v in variants.items() if (v['family']=='trima')==(a.phase=='trima')]
 skipped=[]
 if a.graph=='webcc' and a.phase=='ports':
  skipped=[k for k in selected if variants[k]['mix']==0 and variants[k]['variant']!='D1-direct']
  selected=[k for k in selected if k not in skipped]
 (a.out/'not-measured.json').write_text(json.dumps([dict(key=k,status='not_measured_time_limit',evidence='../suite-v1/webcc-policy-v2/skipped-cells.json') for k in skipped],indent=2)+'\n')
 refs={}
 for key in selected:
  v=variants[key];family=v['family']
  if family=='steptc':
   folder=f'{a.graph}-direct-'+('v1' if a.graph in ['fb','notredame'] else 'continue-v1')
   original=v['variant'] if a.graph!='webcc' or v['variant']!='D3-oa-w4' else 'D2-oa'
   ref=S/folder/f'profile-steptc-{original}/result-1.npy'
  elif family=='trust':
   ref=H/'cpu-graphs-v1/webcc-pruned-reference.npy' if a.graph=='webcc' else S/f'{a.graph}-source-continue-v1'/f'profile-{v["variant"]}/result-1.npy'
  else:
   ref=S/f'{a.graph}-source-continue-'+('v2' if a.graph=='webcc' else 'v1')/'profile-trima/raw-1.npy'
  refs[key]=run('profile-'+key,key,g['input_path'],g['expected_count'],True,ref,g)
 for block in range(3):
  order=list(selected);random.Random(20261022+block).shuffle(order)
  for key in order:run(f'block{block}-{key}',key,g['input_path'],g['expected_count'],False,refs[key],g)
 med={key:statistics.median(r['summary']['median_s'] for r in records if r['phase']=='timing' and r['key']==key) for key in selected}
 comparisons={}
 for key in selected:
  v=variants[key]
  if v['mix']==1:
   base=key.replace('-mix1','-mix0') if v['family']=='trima' else key.removesuffix('-mix')
   comparisons[base+'/'+key]=dict(status='measured',ratio=med[base]/med[key]) if base in med else dict(status='not_measured_time_limit',ratio=None)
 if a.phase=='ports':
  comparisons['steptc-D1-direct/steptc-D2-oa-mix']=dict(status='measured',ratio=med['steptc-D1-direct']/med['steptc-D2-oa-mix'])
  comparisons['steptc-D2-oa-mix/steptc-D3-oa-w4-mix']=dict(status='measured',ratio=med['steptc-D2-oa-mix']/med['steptc-D3-oa-w4-mix'])
 (a.out/'comparison.json').write_text(json.dumps(dict(graph=a.graph,phase=a.phase,seconds=med,comparisons=comparisons),indent=2)+'\n')
save('complete_with_time_limits' if a.graph=='webcc' and a.phase=='ports' else 'complete')
