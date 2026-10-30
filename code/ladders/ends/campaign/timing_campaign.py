"""Task40 768 paired timing cells; fail closed; no prediction scoring."""
from pathlib import Path
import json,hashlib,fcntl,subprocess,sys,os,random,math,traceback,datetime,statistics
import numpy as np
P=Path(__file__).resolve().parent;O=P/'timing';read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,indent=2)+'\n');t.replace(p)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def value(cmd,key):return cmd[cmd.index('--'+key)+1]
def main():
 O.mkdir(exist_ok=False);records=[];active=None;block=None
 with (P/'timing-campaign.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  def state(status):write(O/'status.json',dict(status=status,pid=os.getpid(),passed=len(records),planned=768,block=block,active=active,updated_utc=now()))
  try:
   auth=read(P/'TIMING_AUTHORIZATION.json');assert auth['status']=='authorized'
   root=P.parents[4];assert sha(root/auth['preregistration_path'])==auth['preregistration_sha256']
   assert sha(P/'PREDICTION_REQUIRED.json')==auth['prediction_required_sha256']
   assert sha(P/'graph-replay-v1/COMPLETE.json')==auth['graph_replay_complete_sha256']
   assert sha(P/'correctness-recovery-v1/COMPLETE.json')==auth['correctness_sha256']
   assert read(P/'correctness-recovery-v1/COMPLETE.json')['passed']==232
   frozen=read(P/'TIMING_SOURCE_FROZEN.json')
   def verify_frozen():
    for f,h in frozen.items():assert sha(P/f)==h,('frozen source',f)
   verify_frozen();orders=read(P/'TIMING_ORDER.json');cells=read(P/'TIMING_CELLS.json');assert len(cells)==256 and len(orders)==3
   write(O/'ORDER.json',orders);state('preflight');checks=[]
   for item in cells:
    cmd=item['command'];gate=Path(item['gate']);assert sha(gate/'summary.json')==item['gate_summary_sha256'];assert sha(gate/'config.json')==item['gate_config_sha256']
    cfg=read(gate/'config.json');ref=Path(value(cmd,'reference'));assert sha(ref)==item['reference_sha256']
    arr=np.load(ref);assert arr.shape[0]==220 and sum(int(r[0])+(int(r[1])<<32) for r in arr)==item['expected_count']
    for key in ['input','reference','replay','schedule','prepare-manifest','engine-counts']:
     if '--'+key in cmd:assert Path(value(cmd,key)).is_file(),('missing prepared input',key,value(cmd,key))
    opts={cmd[i][2:].replace('-','_'):cmd[i+1] for i in range(2,len(cmd)-1) if cmd[i].startswith('--') and not cmd[i+1].startswith('--')}
    ignored={'out','reference','reps','replay','engine_counts','counters'}
    for key,val in opts.items():
     if key in cfg and key not in ignored:
      expected=cfg[key]
      if key=='prepare_manifest':assert read(Path(val))==read(Path(expected));continue
      actual=bool(int(val)) if isinstance(expected,bool) else int(val) if isinstance(expected,int) else val
      assert actual==expected,('gate config mismatch',item['graph'],item['variant'],key,actual,expected)
    if item['kind']=='new':
     assert int(value(cmd,'contexts'))==cfg['source_contexts'] and int(value(cmd,'tail'))==cfg['TAIL_ON'] and int(value(cmd,'trisc'))==cfg['TRISC_ON']
     assert cfg['source_cap']==2240 and cfg['hash_mix']==2 and cfg['logical_cache_page_bytes']==1024
    assert value(cmd,'reps')=='3' and '--profile' not in cmd and '--validate-only' not in cmd
    if '--counters' in cmd:assert value(cmd,'counters')=='0'
    checks.append(dict(graph=item['graph'],family=item['family'],variant=item['variant'],gate_verified=True,reference_sha256=item['reference_sha256']))
   write(O/'PREFLIGHT.json',dict(status='pass',configs=256,checks=checks,preregistration_sha256=auth['preregistration_sha256']))
   for order in orders:
    block=order['block'];expected=list(cells);random.Random(20261022+block).shuffle(expected);assert order['seed']==20261022+block and order['cells']==expected
    for position,item in enumerate(order['cells']):
     verify_frozen();name=f"block{block}-{item['graph']}-{item['family']}-{item['variant']}";dst=O/name
     cmd=[str(dst) if x=='__OUT__' else x for x in item['command']];cmd[0]=sys.executable
     active=dict(name=name,position=position,block=block,graph=item['graph'],family=item['family'],variant=item['variant']);state('running');write(O/'active-command.json',dict(command=cmd,cell=active))
     with (O/(name+'.log')).open('x') as log:
      child=subprocess.Popen(cmd,stdout=log,stderr=log);active['pid']=child.pid;state('running');rc=child.wait()
     assert rc==0,('timing cell failure',name,rc)
     s=read(dst/'summary.json');assert s['status']=='pass' and s['per_owner_exact'] and s['counters']==0 and s['warmup_runs']==1 and s['measured_runs']==3 and s['upload_excluded']
     assert s['timing_measured'] and len(s['samples_s'])==3 and all(math.isfinite(x) and x>0 for x in s['samples_s']);assert s['median_s']==statistics.median(s['samples_s'])
     cbfile=dst/('cb-allocation-0.json' if item['kind']=='baseline' else 'cb-allocation.json');cb=read(cbfile);assert cb['total_cb_bytes']==item['cb_bytes']<=1392*1024,('CB mismatch',name,cb['total_cb_bytes'],item['cb_bytes'])
     ref=np.load(value(cmd,'reference'));kind='raw' if (dst/'raw-0.npy').exists() else 'result';receipts=[]
     for rep in range(4):
      arr=np.load(dst/f'{kind}-{rep}.npy');assert np.array_equal(arr[:,:2],ref[:,:2]) and np.all(arr[:,22]==0),('owner count',name,rep)
      counts=[int(r[0])+(int(r[1])<<32) for r in arr];assert len(counts)==220 and sum(counts)==item['expected_count']
      cores=[counts[2*c]+counts[2*c+1] for c in range(110)];want=[int(ref[2*c,0])+(int(ref[2*c,1])<<32)+int(ref[2*c+1,0])+(int(ref[2*c+1,1])<<32) for c in range(110)];assert cores==want
      receipts.append(dict(rep=rep,warmup=rep==0,total=sum(counts),owner220_exact=True,core110_exact=True,count_sha256=hashlib.sha256(json.dumps(counts).encode()).hexdigest()))
     write(dst/'COUNT_RECEIPTS.json',receipts)
     rec=dict(status='pass',name=name,graph=item['graph'],family=item['family'],variant=item['variant'],block=block,position=position,cell=str(dst.relative_to(P)),summary_sha256=sha(dst/'summary.json'),cb_bytes=cb['total_cb_bytes'],gate=item['gate'],finished_utc=now());records.append(rec);write(O/'RECORDS.json',records);active=None;state('running')
    br=[r for r in records if r['block']==block];assert len(br)==256;write(O/f'BLOCK{block}_COMPLETE.json',dict(status='complete',block=block,passed=256,records=br,completed_utc=now()));state('block_complete')
   assert len(records)==768
   write(O/'COMPLETE.json',dict(status='complete',passed=768,failed=0,blocks=3,records=records,preregistration_sha256=auth['preregistration_sha256'],completed_utc=now(),performance_interpretation=False,prediction_scoring=False));state('complete')
  except BaseException as e:
   write(O/'FAILURE.json',dict(error=repr(e),active=active,records=records,traceback=traceback.format_exc(),utc=now()));state('failed');raise
if __name__=='__main__':main()
