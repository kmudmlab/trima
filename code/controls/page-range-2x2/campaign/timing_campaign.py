"""Task36: authorized 204 page cells + 6 empty Count cells; fail closed."""
from pathlib import Path
import json,hashlib,subprocess,sys,traceback,fcntl,datetime,random,os,math,time
import numpy as np
P=Path(__file__).resolve().parent;O=P/'timing';read=lambda p:json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def write(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,indent=2)+'\n');t.replace(p)
def main():
 guard=(P/'timing-controller.lock').open('a');fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
 O.mkdir();records=[];active=None
 def state(s):write(O/'status.json',dict(status=s,pid=os.getpid(),passed=len(records),planned=210,active=active,updated_utc=now()))
 try:
  auth=read(P/'TIMING_AUTHORIZATION.json');cp=read(P/'PREDICTION_REQUIRED.json')
  assert auth['status']=='authorized' and auth['correctness_sha256']==cp['correctness_sha256']
  for rel,h in cp['files'].items():assert sha(P/rel)==h,('checkpoint',rel)
  assert sha(P/'PREREGISTRATION-23.md')==auth['prereg_sha256'] and sha(P/'prediction-task36.json')==auth['prediction_sha256']
  final=read(P.parent/'task35-final-v1/timing/COMPLETE.json');assert final['status']=='complete' and final['passed']==1695 and final['failed']==0
  frozen=read(P/'TIMING_SOURCE_FROZEN.json')
  def verify_sources():
   for rel,h in frozen.items():assert sha(P/rel)==h,('source SHA mismatch',rel)
   for rel,h in read(P/'EXECUTION_FROZEN.json').items():assert sha(P/rel)==h,('correctness source mismatch',rel)
  verify_sources()
  jobs={x['graph']:x for x in read(P/'jobs.json') if not x['fixture']};assert len(jobs)==17
  vs={x['name']:x for x in read(P/'VARIANTS.json')};refs={(x['graph'],x['variant']):x for x in read(P/'ANCHOR_REFERENCES.json')}
  cb={(x['graph'],x['variant']):x['cb_bytes'] for x in read(P/'CB_PLAN.json')}
  base=[dict(kind='page',graph=g,variant=v) for g in jobs for v in vs]+[dict(kind='empty',graph='empty',variant=v) for v in ['B','L7']]
  orders=[]
  for b in range(3):
   cells=[dict(x,block=b) for x in base];random.Random(20261022+b).shuffle(cells);orders.append(cells)
  write(O/'ORDER.json',orders);write(O/'AUTHORIZATION.json',auth);state('running')
  for b,cells in enumerate(orders):
   for pos,cell in enumerate(cells):
    verify_sources();name=f"block{b}-{cell['graph']}-{cell['variant']}";dst=O/name;active=dict(cell,name=name,position=pos,started_utc=now());state('running')
    if cell['kind']=='empty':cmd=[sys.executable,str(P/'code/empty/timing.py'),'--path',cell['variant'],'--out',str(dst)]
    else:
     j=jobs[cell['graph']];v=vs[cell['variant']];ref=refs[(cell['graph'],'L3' if v['direct'] else 'L2')];rp=Path(ref['prior']);assert sha(rp/'summary.json')==ref['summary_sha256']
     cmd=[sys.executable,str(P/'code/baseline/timing.py'),'--input',j['tt_input'],'--out',str(dst),'--expected',str(j['expected_count']),'--engine-counts',str(P/'input-metadata'/f"{j['graph']}.json"),'--reps','3','--chunk-kib','262144','--prune','1','--hash-oa','1','--hash-mix','2','--direct',str(v['direct']),'--lookup-width','1','--page-bytes',str(v['page_bytes']),'--row-cache-kib','16','--col-cache-kib','64','--meta-stage','64','--arena-kib','64','--hash-size','16384','--reference',str(rp/'result-0.npy')]
    write(O/'active-command.json',dict(cell=active,command=cmd));started=time.monotonic()
    with (O/(name+'.log')).open('x') as log:
     child=subprocess.Popen(cmd,stdout=log,stderr=log);active['pid']=child.pid;state('running');rc=child.wait()
    assert rc==0,('device cell failure',name,rc)
    summary=read(dst/'summary.json');assert summary['status']=='pass' and summary['per_owner_exact'] and summary['counters']==0 and summary['warmup_runs']==1 and summary['measured_runs']==3 and summary['upload_excluded']
    assert len(summary['samples_s'])==3 and all(math.isfinite(x) and x>0 for x in summary['samples_s'])
    cf=dst/('cb-allocation.json' if cell['kind']=='empty' else 'cb-allocation-0.json');c=read(cf);assert c['total_cb_bytes']<=1392*1024
    counts=[]
    if cell['kind']=='page':
     assert c['total_cb_bytes']==cb[(cell['graph'],cell['variant'])]
     ref_a=np.load(rp/'result-0.npy')
     for rep in range(4):
      a=np.load(dst/f'result-{rep}.npy');assert np.array_equal(a[:,:2],ref_a[:,:2])
      engines=[int(r[0])+(int(r[1])<<32) for r in a];assert sum(engines)==j['expected_count']
      counts.append(dict(repetition=rep,total=sum(engines),engine_count=220,core_count=110,per_owner_exact=True,counts_sha256=hashlib.sha256(json.dumps(engines).encode()).hexdigest()))
    else:assert summary['zero_count_exact']
    write(dst/'COUNT_RECEIPTS.json',counts)
    records.append(dict(cell,name=name,position=pos,status='pass',summary_sha256=sha(dst/'summary.json'),cb_sha256=sha(cf),CB_bytes=c['total_cb_bytes'],cell_wall_s=time.monotonic()-started,finished_utc=now()))
    write(O/'RECORDS.json',records);active=None;state('running')
   write(O/f'BLOCK{b}_COMPLETE.json',dict(status='complete',block=b,passed=70,records=[r for r in records if r['block']==b],utc=now()))
  assert len(records)==210
  write(O/'COMPLETE.json',dict(status='complete',passed=210,failed=0,page_cells=204,empty_cells=6,blocks=3,records=records,utc=now()));state('complete')
 except BaseException as e:
  write(O/'FAILURE.json',dict(error=repr(e),active=active,records=records,traceback=traceback.format_exc(),utc=now()));state('failed');raise
if __name__=='__main__':main()
