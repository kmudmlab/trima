from pathlib import Path
import sys,json,hashlib,subprocess,fcntl,traceback,datetime,statistics,random
import numpy as np
P=Path(__file__).resolve().parent;O=P/'timing-v1'
rd=lambda p:json.loads(p.read_text())
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(16<<20),b''):h.update(chunk)
 return h.hexdigest()
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def wr(p,d):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2)+'\n');t.replace(p)
def main():
 O.mkdir(exist_ok=False);records=[];active=None
 with (P/'device-campaign.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  def state(status):wr(O/'status.json',dict(status=status,pid=__import__('os').getpid(),passed=len(records),planned=138,active=active,updated_utc=now()))
  try:
   auth=rd(P/'TIMING_AUTHORIZATION.json');assert auth['authorized'] and sha(P/'PREDICTION_REQUIRED.json')==auth['checkpoint_sha256'];cp=rd(P/'PREDICTION_REQUIRED.json');assert sha(P/cp['correctness'])==auth['correctness_sha256']
   commands=rd(P/'TIMING_COMMANDS.json');lookup={(r['graph'],r['family'],r['variant']):r for r in commands};assert len(lookup)==46
   orders=rd(P/cp['planned_order']);assert sha(P/cp['planned_order'])==cp['planned_order_sha256'];wr(O/'ORDER.json',orders)
   frozen=rd(P/'timing-code/SOURCE_FROZEN.json');assert all(sha(P/n)==h for n,h in frozen.items())
   for block in orders:
    b=block['block'];assert block['seed']==20261022+b
    for index,item in enumerate(block['cells']):
     r=lookup[(item['graph'],item['family'],item['variant'])];assert sha(P/r['config'])==r['config_sha256'];assert sha(P/r['profile_report'])==r['profile_report_sha256'];assert sha(P/r['reference'])==r['reference_sha256'];assert all(sha(P/n)==h for n,h in frozen.items())
     inp=Path(r['args'][r['args'].index('--input')+1]);assert sha(inp)==r['input_sha256']
     dst=O/f"block{b}-{r['graph']}-{r['family']}-{r['variant']}";cmd=[sys.executable,r['runner'],*r['args'],'--out',str(dst)]
     active=dict(block=b,index=index,graph=r['graph'],family=r['family'],variant=r['variant'],started_utc=now());state('running');wr(O/'ACTIVE_COMMAND.json',cmd)
     with (O/(dst.name+'.log')).open('x') as log:
      child=subprocess.Popen(cmd,stdout=log,stderr=log,cwd='/home/dmlab/tritt');active['pid']=child.pid;state('running');rc=child.wait()
     assert rc==0,('cell failure',active,rc)
     sm=rd(dst/'summary.json');assert sm['status']=='pass' and sm['counters']==0 and sm['warmup_runs']==1 and sm['measured_runs']==3 and sm['per_owner_exact'];assert len(sm['samples_s'])==3 and sm['median_s']==statistics.median(sm['samples_s'])
     ref=np.load(P/r['reference']);prefix='raw' if r['variant']=='L6' else 'result';evidence=[]
     for rep in range(4):
      raw=dst/f'{prefix}-{rep}.npy';a=np.load(raw);assert np.array_equal(a[:,:2],ref[:,:2]);assert sum(int(x[0])+(int(x[1])<<32) for x in a)==r['expected'];assert not np.any(a[:,22]);evidence.append(dict(repeat=rep,raw_sha256=sha(raw),owner_exact=True,total_exact=True))
     cb=rd(dst/('cb-allocation.json' if r['group']=='locality' else 'cb-allocation-0.json'));assert cb['total_cb_bytes']==r['cb_bytes']<=1392*1024
     wr(dst/'TIMING_VALIDATION.json',dict(status='pass',reference=r['reference'],reference_sha256=r['reference_sha256'],repeats=evidence,cb_plan_exact=True,cb_bytes=r['cb_bytes'],kernel_frozen=True))
     records.append(dict(block=b,index=index,graph=r['graph'],family=r['family'],variant=r['variant'],group=r['group'],status='pass',median_s=sm['median_s'],summary=str((dst/'summary.json').relative_to(P)),summary_sha256=sha(dst/'summary.json'),validation_sha256=sha(dst/'TIMING_VALIDATION.json'),finished_utc=now()));wr(O/'RECORDS.json',records);active=None;state('running')
    wr(O/f'BLOCK{b}_COMPLETE.json',dict(status='pass',block=b,cells=46,finished_utc=now()))
   wr(O/'COMPLETE.json',dict(status='pass',timing_cells=138,records=records,blocks=3,warmup_runs=1,measured_runs=3,counters=0,finished_utc=now()));state('complete')
  except BaseException as e:
   wr(O/'failure.json',dict(error=repr(e),active=active,passed=len(records),traceback=traceback.format_exc()));state('failed');raise
if __name__=='__main__':main()
