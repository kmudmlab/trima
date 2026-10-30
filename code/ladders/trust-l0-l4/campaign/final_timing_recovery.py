"""Final campaign: exclusive sequential device dispatch, Friendster gate at cell boundaries."""
from pathlib import Path
import json,hashlib,fcntl,subprocess,sys,os,random,math,time,traceback,datetime
import numpy as np
P=Path(__file__).resolve().parent;G=P.parent;Q=P/'b-ablation-v1';D=P/'final-timing-code';O=P/'timing-recovery-v1'
read=lambda p:json.loads(p.read_bytes());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,indent=2)+'\n');t.replace(p)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def key(r):return r['group'],r['graph'],r['variant']
def raw_reference(prior):
 paths=sorted(list(prior.glob('result-*.npy'))+list(prior.glob('raw-*.npy')))
 assert paths,('missing reference',str(prior));return paths[0]
def command(r,dst,binding):
 g,v=r['graph'],r['variant'];j=J[g];prior=Path(binding['prior']);ref=raw_reference(prior)
 if r['group'] in ['A','C']:
  common=['--input',j['tt_input'],'--out',dst,'--expected',j['expected_count'],'--engine-counts',P/'input-metadata'/f'{g}.json','--chunk-kib',262144,'--reps',3,'--reference',ref]
  if v in ['L6','L7','T-off','mix0','mix1']:
   base=list(read(P/'prior-FINAL_SETTINGS.json')['cli_base']);base[base.index('--hash-mix')+1]=str({'mix0':0,'mix1':1}.get(v,2))
   return list(map(str,[sys.executable,D/'trima/run.py',*common,*base,'--stage',v,'--aux-rowptr',0,'--tail-merge',int(v!='T-off'),'--pipe-meta',0,'--merge-bytes',j['merge_bytes'],'--no-trisc',0,'--serialize-sources',int(v=='L6'),'--validated-sha',j['input_sha256']]))
  stage=int(v[1]) if len(v)==2 else 5
  cmd=[sys.executable,D/('baseline' if stage<5 else 'trust')/'run.py',*common,'--prune',int(stage>=1),'--hash-oa',int(stage>=2),'--hash-mix',2 if stage>=2 else 0,'--direct',int(stage>=3),'--lookup-width',4 if stage>=4 else 1,'--page-bytes',16384 if stage>=3 else 1024,'--row-cache-kib',16,'--col-cache-kib',64,'--arena-kib',64,'--meta-stage',64,'--hash-size',16384]
  if stage==5:cmd+=['--hash-pool',int(v=='L5-H'),'--merge-bytes',j['merge_bytes']]
  return list(map(str,cmd))
 fam,variant=v.split('-',1);bj=BJ[g];manifest=Q/'prior-graph-replay'/g/f'{fam}-manifest.json';schedule=G/'task22-v1'/fam/('prepared-large' if g=='friendster' else 'prepared')/g/'aux.bin';h=read(manifest)['schedule_sha256'];a=ANCHORS[fam,g] if variant=='anchor' else None
 if a and a['anchor_kind']=='port':
  cmd=[sys.executable,D/'port/run.py','--input',j['tt_input'],'--out',dst,'--expected',j['expected_count'],'--validated-sha',j['input_sha256'],'--reference',ref,'--counters',0,'--reps',3,'--schedule',schedule,'--schedule-sha',h,'--prepare-manifest',manifest,'--replay',G/'task28-v1/anchor-replay'/f'{fam}-{g}.json']
  for k,x in a['options'].items():cmd+=['--'+k.replace('_','-'),x]
  return list(map(str,cmd))
 supply='range' if a else variant.split('-')[0];suffix=None if a or '-' not in variant else variant.split('-',1)[1]
 legacy=bool(a);assert not legacy or a['anchor_kind']=='old_trisc'
 replay=(G/'task28-v1/anchor-trisc-replay-v1'/f'{g}.json') if legacy else (Q/'graph-replay-v2'/g/fam/f'{supply}-{suffix}.json') if suffix else (Q/'prior-graph-replay'/g/f'{fam}-{supply}.json')
 cmd=[sys.executable,D/('family-new' if suffix else 'family')/'run.py','--input',j['tt_input'],'--input-sha',j['input_sha256'],'--schedule',schedule,'--schedule-sha',h,'--expected',j['expected_count'],'--family',fam,'--supply',supply,'--replay',replay,'--reference',ref,'--out',dst,'--reps',3]
 if suffix:cmd+=['--tail',int(suffix!='D-end'),'--trisc',int(suffix=='plus-context'),'--contexts',2 if suffix=='plus-context' else 1]
 if legacy:cmd+=['--legacy-anchor']
 return list(map(str,cmd))
def verify_config(cmd,b):
 prior=Path(b['prior']);assert sha(prior/'summary.json')==b['summary_sha256'],('gate summary SHA',prior)
 # The run-time CB and every immutable option shared by the profile and timing CLI must agree.
 cfg=read(prior/'config.json');opts={cmd[i][2:].replace('-','_'):cmd[i+1] for i in range(2,len(cmd)-1) if cmd[i].startswith('--') and not cmd[i+1].startswith('--')}
 ignored={'out','reference','reps','replay','engine_counts','counters'}
 for k,val in opts.items():
  if k in cfg and k not in ignored:
   want=cfg[k]
   if k=='prepare_manifest':
    assert read(Path(val))==read(Path(want)),('prepare manifest content',val,want);continue
   if isinstance(want,bool):actual=bool(int(val))
   elif isinstance(want,int):actual=int(val)
   else:actual=val
   assert actual==want,('profile/timing option mismatch',k,actual,want,prior)
 for arg in ['--input','--reference','--replay','--schedule','--prepare-manifest','--engine-counts']:
  if arg in cmd:assert Path(cmd[cmd.index(arg)+1]).is_file(),('missing input',arg,cmd[cmd.index(arg)+1])
def main():
 global J,BJ,ANCHORS
 O.mkdir(exist_ok=False);records=read(P/'TIMING_RECOVERY_RECEIPT.json')['records'];active=None;events=[];block=None;friendster_pass=False
 with (P/'final-campaign.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  def state(s):write(O/'status.json',dict(status=s,pid=os.getpid(),block=block,passed=sum(r['status']=='pass' for r in records),refused=sum(r['status']=='refused_capacity' for r in records),active=active,friendster_gate_pass=friendster_pass,updated_utc=now(),planned_timing=1695,planned_refused=21))
  try:
   auth=read(P/'TIMING_AUTHORIZATION_V3.json');assert auth['status']=='authorized' and sha(P/'PREREGISTRATION-22.md')==auth['prereg_sha256']
   frozen=read(P/'FINAL_TIMING_SOURCE_FROZEN_V2.json');proofs=read(P/'TIMING_GATE_BINDINGS.json');bindings={key(r):r for r in proofs};assert len(bindings)==556
   assert sha(P/'TIMING_GATE_BINDINGS.json')==read(P/'TIMING_PARTIAL_CHECKPOINT.json')['bindings_sha256']
   J={r['graph']:r for r in read(P/'jobs-ready.json') if not r['fixture']};BJ={r['graph']:r for r in read(Q/'jobs-28a.json')};ANCHORS={(r['family'],r['graph']):r for r in read(P/'ANCHORS_FROZEN.json')['anchors']}
   orders=read(P/'TIMING_ORDER_V3.json');write(O/'ORDER.json',orders);state('preflight')
   for rel,h in frozen.items():assert sha(P/rel)==h,('source SHA',rel)
   checks=[]
   for r in orders[0]['non_friendster']:
    b=bindings[key(r)];cmd=command(r,O/('preflight-'+r['graph']+'-'+r['variant']),b);verify_config(cmd,b);checks.append(dict(**r,command=cmd,gate=b))
   assert len(checks)==537
   write(O/'PREFLIGHT.json',dict(status='pass',cells=537,checks=checks,prereg_sha256=auth['prereg_sha256']))
   def verify_frozen():
    for rel,h in frozen.items():assert sha(P/rel)==h,('source SHA',rel)
   def friendster_gate(boundary):
    nonlocal active,friendster_pass
    if friendster_pass:return
    if (P/'FRIENDSTER_CPU_FAILURE.json').exists():raise RuntimeError(('Friendster CPU gate failed',read(P/'FRIENDSTER_CPU_FAILURE.json')))
    ready=P/'FRIENDSTER_CPU_READY.json'
    if not ready.exists():return
    proof=read(ready)
    for rel,h in proof['files'].items():assert sha(P/rel)==h,('Friendster CPU transfer SHA',rel)
    assert read(Q/'graph-replay-v2/COMPLETE.json')['passed']==219
    event=dict(kind='friendster_profile_insertion',boundary=boundary,block=block,after_timing_records=len(records),started_utc=now(),profiles=9);events.append(event);write(O/'INSERTIONS.json',events)
    active=dict(kind='friendster_profile',boundary=boundary);state('friendster_profile')
    cmd=[sys.executable,str(Q/'device_graph_batch.py'),'--phase','graphs','--out','device-graphs-friendster-v1','--order','DEVICE_GRAPH_FRIENDSTER_ORDER.json']
    with (O/'friendster-profile.log').open('x') as log:
     child=subprocess.Popen(cmd,stdout=log,stderr=log);active['pid']=child.pid;state('friendster_profile');rc=child.wait()
    assert rc==0,('Friendster device gate failure',rc)
    complete=read(Q/'device-graphs-friendster-v1/COMPLETE.json');assert complete['status']=='pass' and complete['passed']==9
    for r in complete['records']:
     prior=Q/'device-graphs-friendster-v1'/r['name'];assert sha(prior/'summary.json')==r['summary_sha256'];assert read(prior/'CPU_DEVICE_COMPARISON-0.json')['exact'] and read(prior/'COUNT_RECEIPT-0.json')['per_owner_exact']
     b=dict(group='B',graph='friendster',variant=r['family']+'-'+r['supply']+'-'+r['variant'],prior=str(prior),summary_sha256=r['summary_sha256'],CB_bytes=r['cb_bytes']);bindings[key(b)]=b
    assert len(bindings)==565
    for r in orders[0]['friendster_tail']:
     if r['status']=='planned':verify_config(command(r,O/'preflight-friendster',bindings[key(r)]),bindings[key(r)])
    friendster_pass=True;event['completed_utc']=now();event['status']='pass';write(O/'INSERTIONS.json',events)
    write(O/'FRIENDSTER_GATE_PASS.json',dict(status='pass',profiles=9,checkpoint_sha256=sha(Q/'device-graphs-friendster-v1/COMPLETE.json'),eligible_friendster_configs=28,bindings=[b for b in bindings.values() if b['graph']=='friendster']));active=None;state('running')
   def run_cell(r,b,position):
    nonlocal active
    name=f"block{b}-{r['group']}-{r['graph']}-{r['variant']}";dst=O/name
    if any(x['name']==name for x in records):return
    if r['status']=='refused_capacity':
     dst.mkdir();receipt=dict(**r,name=name,block=b,position=position,configuration_unchanged=True);write(dst/'REFUSED.json',receipt);records.append(receipt);return
    binding=bindings[key(r)];verify_frozen();cmd=command(r,dst,binding);verify_config(cmd,binding)
    active=dict(name=name,block=b,position=position,kind='timing',graph=r['graph'],variant=r['variant']);state('running');write(O/'active-command.json',dict(command=cmd,cell=active))
    with (O/(name+'.log')).open('x') as log:
     child=subprocess.Popen(cmd,stdout=log,stderr=log);active['pid']=child.pid;state('running');rc=child.wait()
    assert rc==0,('timing cell failure',name,rc)
    s=read(dst/'summary.json');assert s['status']=='pass' and s['per_owner_exact'] and s['counters']==0 and s['warmup_runs']==1 and s['measured_runs']==3 and s['upload_excluded']
    assert len(s['samples_s'])==3 and all(math.isfinite(x) and x>0 for x in s['samples_s'])
    cbfile=dst/('cb-allocation.json' if r['group']=='B' else 'cb-allocation-0.json');cb=read(cbfile);assert cb['total_cb_bytes']==binding['CB_bytes']<=1392*1024,('runtime CB mismatch',name,cb['total_cb_bytes'],binding['CB_bytes'])
    reference=np.load(raw_reference(Path(binding['prior'])));kind='raw' if (dst/'raw-0.npy').exists() else 'result';counts=[]
    for rep in range(4):
     a=np.load(dst/f'{kind}-{rep}.npy');assert np.array_equal(a[:,:2],reference[:,:2]) and np.all(a[:,22]==0),('per-owner mismatch',name,rep)
     count=[int(x[0])+(int(x[1])<<32) for x in a];assert sum(count)==J[r['graph']]['expected_count'];counts.append(dict(rep=rep,total=sum(count),owner_count=len(count),count_sha256=hashlib.sha256(json.dumps(count).encode()).hexdigest(),per_owner_exact=True))
    write(dst/'COUNT_RECEIPTS.json',counts)
    receipt=dict(r,status='pass',name=name,block=b,position=position,summary_sha256=sha(dst/'summary.json'),CB_bytes=cb['total_cb_bytes'],gate=binding['prior'],cell=str(dst.relative_to(P)),finished_utc=now());records.append(receipt);write(O/'RECORDS.json',records);active=None;state('running')
   for order in orders:
    block=order['block'];state('running')
    for i,r in enumerate(order['non_friendster']):
     # First timing cell starts before optional pending Friendster profiles.
     if records and not any(x['name']==f"block{block}-{r['group']}-{r['graph']}-{r['variant']}" for x in records):friendster_gate(dict(segment='non_friendster',next_index=i))
     run_cell(r,block,dict(segment='non_friendster',index=i))
    while not friendster_pass:
     friendster_gate(dict(segment='friendster_tail',next_index=0))
     if not friendster_pass:state('waiting_friendster_cpu');time.sleep(15)
    events.append(dict(kind='friendster_timing_tail',block=block,after_timing_records=len(records),started_utc=now(),nominal=35,execute=28,refused=7));write(O/'INSERTIONS.json',events)
    for i,r in enumerate(order['friendster_tail']):run_cell(r,block,dict(segment='friendster_tail',index=i))
    br=[r for r in records if r['block']==block];assert len(br)==572 and sum(r['status']=='pass' for r in br)==565
    write(O/f'BLOCK{block}_COMPLETE.json',dict(status='complete',block=block,passed=565,refused=7,records=br,completed_utc=now(),protocol_deviation='Friendster 35 records appended after 537 shuffled eligible cells; profile9 inserted at recorded idle boundary.'))
    state('block_complete_sync_pending')
    while not (O/f'BLOCK{block}_SYNCED.json').exists():time.sleep(10)
   write(O/'COMPLETE.json',dict(status='complete',passed=1695,refused=21,failed=0,blocks=3,records=records,protocol_deviations=events,performance_summary_disclosed=False));write(P/'timing/COMPLETE.json',dict(read(O/'COMPLETE.json'),recovery_path=str(O.relative_to(P)),original_failure_preserved=True));state('complete')
  except BaseException as e:
   write(O/'FAILURE.json',dict(error=repr(e),active=active,records=records,traceback=traceback.format_exc(),utc=now()));write(O/'FAILURE_IMPACT.md','관문 또는 셀 실패로 후속 dispatch를 즉시 정지했다. 완료 셀 원자료는 보존한다. 실패 원인과 다른 셀에 대한 영향은 검토 전 미확정이며, 독립성 판단 없이 다른 셀을 계속 실행하지 않는다.\n');state('failed');raise
if __name__=='__main__':main()
