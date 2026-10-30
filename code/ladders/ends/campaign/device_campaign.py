"""Task40 correctness only. Full CPU gates are required; no timing launch exists."""
from pathlib import Path
import json,hashlib,subprocess,fcntl,sys,traceback,os,time
import numpy as np
P=Path(__file__).resolve().parent;O=P/'correctness-v1';read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,indent=2)+'\n');t.replace(p)
def main():
 assert read(P/'cpu-fixtures-v1/COMPLETE.json')['checks']==888
 def validate_replays(proof,full):
  required={j['graph'] for j in read(P/'jobs.json') if not j['fixture'] and (full or j['graph']!='friendster')}
  variants={v['name'] for v in read(P/'VARIANTS.json')}
  assert proof['passed']==len(required)*8 and proof['status']=='pass'
  assert {(r['graph'],r['variant']) for r in proof['records']}=={(g,v) for g in required for v in variants}
  assert len(proof['records'])==proof['passed']
  for r in proof['records']:
   assert r['status']=='pass' and r['physical_QBW_exact']
   d=P/'graph-replay-v1'/r['graph']
   assert sha(d/(r['variant']+'.json'))==r['replay_sha256']
   assert sha(d/(r['variant']+'-expected.json'))==r['expected_sha256']
 validate_replays(read(P/'CPU_READY_15.json'),False)
 assert read(P/'COMPARATOR_GATE_REUSE.json')['configs']==96
 assert read(P/'protocol-context-v1/COMPLETE.json')['schedules']==216
 assert read(P/'cpu-capacity-v1/COMPLETE.json')['status']=='pass'
 assert read(P/'preprocessor-v1/COMPLETE.json')['checks']==16
 O.mkdir(exist_ok=False);records=[];active=None
 with (P/'device-campaign.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:
   frozen=read(P/'SOURCE_FROZEN.json');order=read(P/'DEVICE_ORDER.json');assert len(order)==232
   write(O/'ORDER.json',order)
   jobs={j['graph']:j for j in read(P/'jobs.json')};anchors={a['graph']:a for a in read(P/'ANCHORS_FROZEN.json')['trust']};refs=read(P/'COUNTS_REFERENCE.json')
   def state(s):write(O/'status.json',dict(status=s,pid=os.getpid(),passed=len(records),planned=232,active=active,timing_started=False))
   state('preflight')
   friendster_ready=False
   for item in order:
    assert not (P/'UPSTREAM_FAILURE.json').exists(), 'CPU replay failed; no further device cells'
    if item['graph']=='friendster' and not friendster_ready:
     active=dict(graph='friendster',gate='waiting for all 128 CPU replays');state('waiting_friendster_cpu')
     while not (P/'CPU_ALL_READY.json').exists():
      assert not (P/'UPSTREAM_FAILURE.json').exists(), 'CPU replay failed while waiting'
      time.sleep(5)
     gate=read(P/'CPU_ALL_READY.json')
     assert sha(P/'graph-replay-v1/COMPLETE.json')==gate['complete_sha256']
     validate_replays(read(P/'graph-replay-v1/COMPLETE.json'),True);friendster_ready=True
    for f,h in frozen.items():assert sha(P/f)==h,('source changed',f)
    g=item['graph'];j=jobs[g];dst=O/item['name'];active=dict(item);state('running')
    if item['kind']=='family':
     inp=P/'fixtures'/f'{g}.csr' if j['fixture'] else Path(j['tt_input'])
     expected=P/item['expected']
     cmd=[sys.executable,str(P/'code/profile_family.py'),'--input',str(inp),'--input-sha',j['input_sha256'],'--out',str(dst),'--expected',str(j['expected_count']),'--family','trust','--supply',item['supply'],'--replay',str(expected),'--tail',str(item['tail']),'--trisc',str(item['trisc']),'--contexts',str(item['contexts']),'--counters',str(item['counters']),'--launches',str(item['launches']),'--stress',str(item['stress'])]
    else:
     a=anchors[g] if item['variant']=='anchor' else None
     opts=a['options'] if a else dict(page_bytes=1024,row_cache_kib=16,col_cache_kib=64,bucket_cap=100,hash_size=16384,prune=0,hash_oa=0,hash_mix=0,direct=0,lookup_width=1,meta_stage=64,arena_kib=64,chunk_kib=262144)
     expected=P/(a['expected'] if a else f'baseline-expected/{g}-L0.json')
     cmd=[sys.executable,str(P/'code/baseline/profile.py'),'--input',j['tt_input'],'--out',str(dst),'--expected',str(j['expected_count']),'--engine-counts',str(P/'input-metadata'/f'{g}.json'),'--profile','--reps','1']
     for k,v in opts.items():cmd+=['--'+k.replace('_','-'),str(v)]
    write(O/'active-command.json',dict(command=cmd,cell=item))
    with (O/(item['name']+'.log')).open('x') as log:
     child=subprocess.Popen(cmd,stdout=log,stderr=log);active['pid']=child.pid;state('running');rc=child.wait()
    assert rc==0,('device cell failure',item['name'],rc)
    summary=read(dst/'summary.json');assert summary['status']=='pass' and summary['timing_measured']==False
    if item['kind']=='family':
     for k in range(item['launches']):
      assert read(dst/f'CPU_DEVICE_COMPARISON-{k}.json')['exact']
      assert read(dst/f'COUNT_RECEIPT-{k}.json')['per_owner_exact']
     cb=read(dst/'cb-allocation.json');assert cb['total_cb_bytes']==item['cb_bytes']<=1392*1024
    else:
     arr=np.load(dst/'result-0.npy');val=lambda r,k:int(r[k])+(int(r[k+1])<<32)
     counts=[val(r,0) for r in arr];assert counts==refs[g]['counts220'],('baseline owner counts',g,item['variant'])
     obs=[[val(r,k) for k in [32,34,36,38,40,4]] for r in arr];want=read(expected)
     assert obs==want['engine220'],('baseline Q/B/W/candidates',g,item['variant'])
     write(dst/'COMPARISON.json',dict(status='pass',counts220=counts,observed=obs,expected_sha256=sha(expected),owner_exact=True,QBW_candidate_exact=True))
     cb=read(dst/'cb-allocation-0.json');assert cb['total_cb_bytes']==summary['l1_bytes']<=1392*1024 and cb['runtime_size_verified']
    records.append(dict(**item,status='pass',summary_sha256=sha(dst/'summary.json'),runtime_cb_bytes=cb['total_cb_bytes']));write(O/'RECORDS.json',records);active=None;state('running')
   assert friendster_ready
   write(O/'COMPLETE.json',dict(status='pass',passed=232,failed=0,records=records,timing_started=False))
   checkpoint=dict(status='PREDICTION_REQUIRED',correctness_sha256=sha(O/'COMPLETE.json'),cpu_checks=888,cpu_replays=128,device_passed=232,timing_planned=768,timing_authorized=False,pilot_timing_omitted=True,source_sha256=sha(P/'SOURCE_FROZEN.json'),anchors_sha256=sha(P/'ANCHORS_FROZEN.json'),next='Wait for prediction commit and explicit timing start signal.')
   write(P/'PREDICTION_REQUIRED.json',checkpoint);state('prediction_required')
  except BaseException as e:
   write(O/'FAILURE.json',dict(error=repr(e),active=active,records=records,traceback=traceback.format_exc()));state('failed');raise
if __name__=='__main__':main()
