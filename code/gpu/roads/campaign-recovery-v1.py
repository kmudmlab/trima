"""Task42: exact gpu-ranking-v3 binaries and launch arguments on frozen road CSR."""
from pathlib import Path
import json,hashlib,fcntl,subprocess,sys,os,socket,time,datetime,random,statistics,traceback,csv,math
from contention_state import snapshot,save_snapshot
import xml.etree.ElementTree as ET
P=Path(__file__).resolve().parent;ROOT=Path('/data0/hmpark/gpu_tt_portability_20261021');O=P/'timing';REC=P/'recovery-v1'
rd=lambda p:json.loads(p.read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(16<<20),b''):h.update(b)
 return h.hexdigest()
def wr(p,d):
 t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n');t.replace(p)
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def main():
 assert socket.gethostname()=='dmlab-bear0';assert os.getpriority(os.PRIO_PROCESS,0)>=10
 O.mkdir(exist_ok=True);assert not (P/'COMPLETE.json').exists()
 with (REC/'RUN_STARTED.json').open('x') as f:json.dump(dict(pid=os.getpid(),utc=now()),f)
 prior_failure=rd(P/'FAILURE.json');records=prior_failure['records'].copy();active=None;start=now();clock=time.monotonic()
 for path,h in rd(REC/'PRESERVED_FILES.json').items():assert sha(P/path)==h,('preserved file changed',path)
 for r in records:
  assert r['status']=='pass' and sha(P/r['summary'])==r['summary_sha256'] and sha(P/r['summary'].replace('summary.json','stdout.log'))==r['stdout_sha256']
  summary=rd(P/r['summary']);assert summary['count_exact'] and len(summary['samples'])==4 and all(x['count']==summary['expected_count'] for x in summary['samples'])
 assert len(records)==3 and all(r['phase']=='verification' for r in records)

 def state(status,a=None):
  wr(REC/'status.json',dict(status=status,pid=os.getpid(),active=active if a is None else a,verification_passed=sum(r['phase']=='verification' for r in records),timing_passed=sum(r['phase']=='timing' for r in records),planned_timing=36,planned_verification=12,started_utc=start,updated_utc=now()))
 state('waiting_for_locks')
 with (ROOT/'cpu-or-gpu.lock').open('a') as hostlock,(ROOT/'gpu.lock').open('a') as gpulock:
  fcntl.flock(hostlock,fcntl.LOCK_EX);fcntl.flock(gpulock,fcntl.LOCK_EX)
  try:
   auth=rd(P/'AUTHORIZATION.json');assert auth['commit']=='9c562351' and sha(P/'PREREGISTRATION-28.snapshot.md')==auth['registration_sha256']
   bins=rd(P/'binary-manifest.json');prior=rd(ROOT/'gpu-ranking-v3/binary-manifest.json');assert bins==prior
   for family,b in bins.items():assert sha(b['path'])==b['sha256'],('binary changed',family)
   graphs=rd(P/'inputs.json');assert len(graphs)==3
   for g in graphs:
    assert sha(g['input_path'])==g['input_sha256'],('input hash',g['graph'])
    oracle=rd(P/'inputs'/(g['graph']+'-oracle.json'));assert oracle['merge_count']==oracle['wedge_count']==g['expected_count']
   wr(REC/'INPUT_VERIFIED.json',dict(status='pass',graphs=graphs,binaries=bins,checked_utc=now()))
   text,xml,initial=snapshot();(REC/'nvidia-smi-initial.txt').write_text(text);(REC/'nvidia-smi-initial.xml').write_text(xml);wr(REC/'GPU_INITIAL.json',initial)
   assert len(initial['devices'])==1 and 'RTX 4080' in initial['devices'][0]['name']
   order=[]
   for block in range(3):
    cells=[dict(graph=g['graph'],family=f) for g in graphs for f in ['trust','tricore','wetric','steptc']];random.Random(20261022+block).shuffle(cells);order.append(dict(block=block,seed=20261022+block,cells=cells))
   assert rd(P/'ORDER.json')==order,'original shuffled order changed'
   wr(REC/'ORDER.json',order)
   def command(family,g):
    cmd=[bins[family]['path']]
    if family=='wetric':return cmd+['run',g['input_path'],'10','8192','3',str(g['expected_count'])]
    return cmd+[g['input_path'],str(g['expected_count'])]+([] if family=='steptc' else ['3'])
   def run(phase,g,family,block=None,index=None):
    nonlocal active
    name=(f'verify-{g["graph"]}-{family}' if phase=='verification' else f'block{block}-{g["graph"]}-{family}')
    found=[r for r in records if r['phase']==phase and r['graph']==g['graph'] and r['family']==family and r['block']==block]
    if found:
     assert len(found)==1 and found[0]['index']==index
     return
    root=REC/'attempts';root.mkdir(exist_ok=True);dst=root/(name+'-attempt1');dst.mkdir(exist_ok=False)
    cmd=command(family,g);assert sha(bins[family]['path'])==bins[family]['sha256']
    active=dict(name=name,phase=phase,graph=g['graph'],family=family,block=block,index=index,command=cmd);state('recording_GPU_state')
    before=save_snapshot(dst,'before')
    wr(dst/'COMMAND.json',dict(command=cmd,binary_sha256=bins[family]['sha256'],input_sha256=g['input_sha256'],protocol='fresh process; warmup1+3; resident_s; counters off',nice=os.getpriority(os.PRIO_PROCESS,0),block=block,index=index))
    active['started_utc']=now()
    with (dst/'stdout.log').open('x') as log:
     child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT);active['pid']=child.pid;state('running');rc=child.wait()
    after=save_snapshot(dst,'after')
    contention=dict(allowed_by_user=True,before=bool(before['busy']),after=bool(after['busy']),observed=bool(before['busy'] or after['busy']),before_processes=before['busy'],after_processes=after['busy'],before_utilization=before['utilization'],after_utilization=after['utilization'],observation_scope='cell boundaries only; no continuous sampling; no exclusion due to contention')
    wr(dst/'CONTENTION.json',contention)
    samples=[]
    for line in (dst/'stdout.log').read_text().splitlines():
     try:r=json.loads(line)
     except json.JSONDecodeError:continue
     if r.get('kind')=='sample':samples.append(r)
    assert rc==0,(name,rc)
    assert len(samples)==4 and samples[0]['warmup'] and not any(r['warmup'] for r in samples[1:]),('warmup/repetitions',name)
    assert all(r['count']==g['expected_count'] for r in samples),('count mismatch',name)
    if family=='wetric':assert all(r['spread']==10 and r['adjacency']==8192 for r in samples)
    values=[r['resident_s'] for r in samples[1:]];assert all(math.isfinite(v) and v>0 for v in values)
    s=dict(status='pass',contention=contention,phase=phase,graph=g['graph'],family=family,block=block,index=index,command=cmd,returncode=rc,samples=samples,median_s=statistics.median(values),expected_count=g['expected_count'],count_exact=True,input_sha256=g['input_sha256'],binary_sha256=bins[family]['sha256'],timing='resident_s: Count launch/synchronize/reduction/readback; input upload and preprocessing excluded',started_utc=active['started_utc'],finished_utc=now())
    wr(dst/'summary.json',s);records.append(dict(phase=phase,graph=g['graph'],family=family,block=block,index=index,status='pass',median_s=s['median_s'],summary=str((dst/'summary.json').relative_to(P)),summary_sha256=sha(dst/'summary.json'),stdout_sha256=sha(dst/'stdout.log'),finished_utc=s['finished_utc']));wr(REC/'RECORDS.json',records);active=None;state('running');print('PASS',name,flush=True)
   for g in graphs:
    for f in ['trust','tricore','wetric','steptc']:run('verification',g,f)
   wr(P/'verification/COMPLETE.json',dict(status='complete',passed=12,records=records.copy(),completed_utc=now()))
   for b in order:
    for i,c in enumerate(b['cells']):
     g=next(g for g in graphs if g['graph']==c['graph']);run('timing',g,c['family'],b['block'],i)
    wr(O/f'BLOCK{b["block"]}_COMPLETE.json',dict(status='complete',block=b['block'],passed=12,completed_utc=now()))
   assert len(records)==48
   tt={(r['graph'],r['family']):r for r in rd(P/'TT_FROZEN.json')['rows']};table=[]
   for g in graphs:
    med={}
    for fam in bins:
     vals=[r['median_s'] for r in records if r['phase']=='timing' and r['graph']==g['graph'] and r['family']==fam];assert len(vals)==3;med[fam]=statistics.median(vals)
    for fam,t in med.items():
     old=tt[(g['graph'],fam)]
     table.append(dict(graph=g['graph'],family=fam,gpu_status='measured',gpu_median_s=t,gpu_rank=1+sum(x<t for x in med.values()),**{k:old[k] for k in ['tt_variant','tt_median_s','tt_rank','tt_source','tt_scope']}))
   wr(P/'gpu-vs-tt.json',table)
   fields=['graph','family','gpu_status','gpu_median_s','gpu_rank','tt_variant','tt_median_s','tt_rank','tt_source','tt_scope']
   with (P/'gpu-vs-tt.csv').open('x',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(table)
   contention_rows=[]
   for r in records:
    dst=(P/r['summary']).parent;summary=rd(dst/'summary.json')
    before=rd(dst/'gpu-state-before.json');after=rd(dst/'gpu-state-after.json')
    contention_rows.append(dict(graph=r['graph'],family=r['family'],phase=r['phase'],block=r['block'],index=r['index'],summary=r['summary'],contention_before=bool(before['busy']),contention_after=bool(after['busy']),contention_observed=bool(before['busy'] or after['busy']),before_pids=';'.join(str(x['pid']) for x in before['busy']),after_pids=';'.join(str(x['pid']) for x in after['busy']),before_utilization=json.dumps(before.get('utilization')),after_utilization=json.dumps(after.get('utilization'))))
   wr(P/'CONTENTION.json',contention_rows)
   with (P/'CONTENTION.csv').open('x',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(contention_rows[0]));writer.writeheader();writer.writerows(contention_rows)
   complete=dict(status='complete',contention_allowed=True,contended_timing_cells=sum(r['phase']=='timing' and r['contention_observed'] for r in contention_rows),contended_verification_cells=sum(r['phase']=='verification' and r['contention_observed'] for r in contention_rows),historical_invalid_attempts=1,reused_verification_cells=3,recovery_source_failure_sha256=sha(P/'FAILURE.json'),verification_passed=12,timing_passed=36,failed=0,blocks=3,records=records,started_utc=start,completed_utc=now(),elapsed_s=time.monotonic()-clock,registration_sha256=auth['registration_sha256'],table_sha256=sha(P/'gpu-vs-tt.csv'),display_condition='사용자 승인에 따라 디스플레이 및 외부 GPU 계산 점유를 허용; 셀 전후 contention 표시 참조',interpretation=False,prediction_scoring=False)
   wr(O/'COMPLETE.json',complete);wr(P/'COMPLETE.json',complete);state('complete')
  except BaseException as e:
   wr(REC/'FAILURE.json',dict(error=repr(e),active=active,records=records,traceback=traceback.format_exc(),utc=now()));state('failed');raise
if __name__=='__main__':main()
