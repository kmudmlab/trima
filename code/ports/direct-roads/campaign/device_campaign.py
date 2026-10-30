"""작업14: 준비된 CPU oracle → device fixture → profile/Q 비교 → timing. 실패 시 정지."""
import argparse,csv,hashlib,json,os,random,statistics,subprocess,sys,time
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent;G=P.parent;E=G.parents[1];R=G/'locality-v1';PREP=R/'device-prepared-v2'
FAMILIES={'steptc':('steptc','steptc-direct',1024),'wetric':('wetric','wetric-direct',256),'tricore':('tricore-coo','tricore-coo-direct',256)}
PRED='d8e4c4f02ab041cb9b7024d2fe10059654dbf72169f35299c8af4138a7bed512'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,d):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n');t.replace(p)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 records=[];fixtures=[];profiles={};start_ticks=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]
 def save(status,active=None):write(a.out/'status.json',dict(status=status,pid=os.getpid(),start_ticks=start_ticks,records=records,fixtures=fixtures,active=active,updated_unix=time.time()))
 def run(graph,family,variant,phase,block=None):
  fixture=phase=='fixture';name=f'{phase}-{graph}-{family}-{variant}'+(f'-b{block}' if block is not None else '')
  prep=PREP/(f'fixture-{graph}-{family}-{variant}-e220' if fixture else f'{graph}-{family}-{variant}')
  manifest=json.loads((prep/'manifest.json').read_text());inp=E/'cpu-validation'/f'{graph}.csr' if fixture else R/'inputs-v1'/f'{graph}.csr'
  meta=json.loads(inp.with_suffix('.json').read_text());mode=FAMILIES[family][variant!='base'];page=FAMILIES[family][2]
  level=3 if family=='tricore' and variant=='base' else 2
  ref=prep/'reference.npy';dst=a.out/name;counter=phase!='timing'
  cmd=[sys.executable,str(P/'code/direct/run_port.py'),'--input',str(inp),'--out',str(dst),'--prepared',str(prep/'manifest.json'),'--validated-sha',manifest['input_sha256'],'--expected',str(meta['count']),'--mode',mode,'--opt-level',str(level),'--page-bytes',str(page),'--reference',str(ref),'--counters',str(int(counter)),'--reps','1' if counter else '3']
  if counter:cmd+=['--candidate-reference',str(ref)]
  started=time.time()
  with (a.out/(name+'.log')).open('x') as f:
   child=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT);save('running',dict(name=name,pid=child.pid,command=cmd));rc=child.wait()
  rec=dict(name=name,phase=phase,graph=graph,family=family,variant=variant,block=block,returncode=rc,wall_s=time.time()-started,status='failed' if rc else 'pending_validation',command=cmd)
  (fixtures if fixture else records).append(rec);save('running');assert rc==0,name
  summary=json.loads((dst/'summary.json').read_text());assert summary['status']=='pass';rec['median_s']=summary['median_s']
  if counter:
   raw=np.load(dst/'result-1.npy')
   vec=lambda w:[int(r[w])+(int(r[w+1])<<32) for r in raw]
   total=lambda w:sum(vec(w))
   c=dict(count=total(0),engine_counts=vec(0),jobs=total(2),candidates=total(4),engine_candidates=vec(4),probes=total(6),row_pages=total(8),col_pages=total(10),aux_pages=total(12),range_requests_row_col_aux=[total(w) for w in [32,34,36]],range_bytes_row_col_aux=[total(w) for w in [38,40,42]],wait_calls=total(44),target_batches=total(46),metadata_batches=total(48))
   info=manifest['info'];assert c['engine_counts']==info['engine_counts'] and c['engine_candidates']==info['engine_candidates']
   key=(graph,family)
   if variant!='base':
    base=profiles[key]['base']['counters'];assert c['engine_counts']==base['engine_counts'] and c['engine_candidates']==base['engine_candidates']
   cfg=json.loads((dst/'config.json').read_text());profile=dict(graph=graph,family=family,variant=variant,counters=c,input_sha256=manifest['input_sha256'],l1_bytes=cfg['l1_bytes'],page_bytes=page)
   profiles.setdefault(key,{})[variant]=profile;write(dst/'profile.json',profile)
  rec['status']='pass';save('running');print('PASS',name,flush=True)
 try:
  assert sha(E/'model/predictions-V4-road-cpu.json')==PRED
  assert sha(R/'selection.json')=='a21047224300656767f57846d191ec1e87377c8f43749179dc016ec15eb130dd'
  prepared=json.loads((PREP/'summary.json').read_text());assert prepared['status']=='pass' and prepared['checks']==72
  for r in prepared['records']:assert sha(PREP/r['name']/'manifest.json')==r['manifest_sha256']
  validation=json.loads((PREP/'cross-validation.json').read_text());assert validation['status']=='pass'
  for fx in ['clique140','long-collision-boundary','random12']:
   for family in FAMILIES:
    for variant in ['base','D1-direct']:run(fx,family,variant,'fixture')
  graphs=['roadNet-PA','roadNet-TX','roadNet-CA']
  for graph in graphs:
   for family in FAMILIES:
    for variant in ['base','D1-direct']:run(graph,family,variant,'profile')
  comparison=[];io_comparison=[]
  for cpu in json.loads((R/'selection.json').read_text())['rows']:
   graph,family=cpu['graph'],cpu['family'];v=profiles[(graph,family)];b=v['base']['counters'];d=v['D1-direct']['counters']
   qb=sum(b[k] for k in ['row_pages','col_pages','aux_pages']);qd=sum(d['range_requests_row_col_aux'])
   row=dict(graph=graph,family=family,Q_base_cpu=cpu['Q_base_cpu'],Q_D1_cpu=cpu['Q_D1_cpu'],Q_base_device=qb,Q_D1_device=qd,delta_base=qb-cpu['Q_base_cpu'],delta_D1=qd-cpu['Q_D1_cpu'])
   row.update(relative_delta_base=row['delta_base']/cpu['Q_base_cpu'],relative_delta_D1=row['delta_D1']/cpu['Q_D1_cpu'],exact=row['delta_base']==0 and row['delta_D1']==0)
   if not row['exact']:row['difference_explanation']='CPU replay와 장치 카운터 차이 관찰; 원인은 아직 미확인. 동결 CPU 예측은 변경하지 않고 차이를 공개한다.'
   comparison.append(row)
   for variant in ['base','D1-direct']:
    c=v[variant]['counters'];observed=[c['row_pages'],c['col_pages'],c['aux_pages'],*c['range_requests_row_col_aux'],*c['range_bytes_row_col_aux'],c['wait_calls'],c['target_batches'],c['metadata_batches']]
    expected=json.loads((R/'candidate-replay-v1'/f'{graph}-{family}-{variant}'/'stdout.json').read_text())['io']
    io_comparison.append(dict(graph=graph,family=family,variant=variant,cpu=expected,device=observed,delta=[a-b for a,b in zip(observed,expected)],exact=observed==expected))
  write(a.out/'cpu-device-request-comparison.json',dict(status='complete',selection_sha256=sha(R/'selection.json'),prediction_sha256=PRED,rows=comparison,exact_pairs=sum(r['exact'] for r in comparison)))
  write(a.out/'cpu-device-io-comparison.json',dict(status='complete',rows=io_comparison,exact_cells=sum(r['exact'] for r in io_comparison)))
  fields=[k for k in comparison[0] if k!='difference_explanation']
  with (a.out/'cpu-device-request-comparison.csv').open('x') as f:
   w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(comparison)
  text=['# 작업14 CPU↔장치 요청 비교 (timing 전 기록)','',f'정확 일치 {sum(r["exact"] for r in comparison)}/9쌍. 예측 SHA: `{PRED}`.','','| 그래프 | 계열 | CPU Q_base | 장치 Q_base | CPU Q_D1 | 장치 Q_D1 |','|---|---|---:|---:|---:|---:|']
  text+=['| '+' | '.join(str(r[k]) for k in ['graph','family','Q_base_cpu','Q_base_device','Q_D1_cpu','Q_D1_device'])+' |' for r in comparison]
  (a.out/'CPU_DEVICE_COMPARISON.md').write_text('\n'.join(text)+'\n')
  for block in range(3):
   jobs=[(g,f,v) for g in graphs for f in FAMILIES for v in ['base','D1-direct']];random.Random(20261022+block).shuffle(jobs)
   for g,f,v in jobs:run(g,f,v,'timing',block)
  med={f'{g}/{f}/{v}':statistics.median(r['median_s'] for r in records if r['phase']=='timing' and (r['graph'],r['family'],r['variant'])==(g,f,v)) for g in graphs for f in FAMILIES for v in ['base','D1-direct']}
  write(a.out/'timing-summary.json',dict(status='complete',median_seconds=med,base_over_D1={f'{g}/{f}':med[f'{g}/{f}/base']/med[f'{g}/{f}/D1-direct'] for g in graphs for f in FAMILIES},comparison_recorded_before_timing=True,prediction_sha256=PRED));save('complete')
 except BaseException as e:save('failed');write(a.out/'failure.json',dict(error=repr(e)));raise
if __name__=='__main__':main()
