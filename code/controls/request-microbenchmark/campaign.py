#!/usr/bin/env python3
"""장치 유휴에서 shared lock을 유지한 1시간 한도 campaign. 셀 강제 종료 없음."""
import argparse,fcntl,hashlib,json,os,random,statistics,subprocess,sys,time
from pathlib import Path
P=Path(__file__).resolve().parent;G=P.parent;E=G.parents[1]
SIZES=[64,128,256,512,1024,2048,4096,8192,16384];BATCHES=[1,2,4,8,16,32]
REGIMES=[(1,1,'random'),(110,2,'random'),(110,2,'contiguous')]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n');t.replace(p)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False);records=[];started=None
 def save(status,active=None):write(a.out/'status.json',dict(status=status,pid=os.getpid(),active=active,records=records,device_budget_s=3600,started_unix=started,updated_unix=time.time()))
 save('waiting_for_idle_device');lock=(G.parent/'hardware.lock').open('a')
 while True:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:time.sleep(30);continue
  owners=subprocess.run(['fuser','/dev/tenstorrent/0'],capture_output=True,text=True)
  assert owners.returncode in [0,1]
  if owners.returncode==1 and not owners.stdout.strip():break
  fcntl.flock(lock,fcntl.LOCK_UN);time.sleep(30)
 started=time.time();deadline=time.monotonic()+3600
 try:
  cpu=json.loads((P/'cpu-validation.json').read_text());assert cpu['status']=='pass'
  for name,d in cpu['source_sha256'].items():assert sha(P/name)==d
  sources=[*P.glob('*.py'),P/'kernel.cpp',E/'NOC_MICROBENCH_DESIGN.md']
  frozen={str(p):sha(p) for p in sources};write(a.out/'manifest.json',dict(status='frozen_before_first_device_cell',source_sha256=frozen,regimes=REGIMES,sizes=SIZES,batches=BATCHES,planned_timing_cells=486,lock_inode=os.fstat(lock.fileno()).st_ino))
  def run(name,cores,engines,pattern,size,batch,block=0,kind='timing'):
   assert all(sha(Path(p))==v for p,v in frozen.items()),'Source changed during experiment'
   reserve=max([r['wall_s'] for r in records[-6:]] or [30])*2+60
   if time.monotonic()+reserve>=deadline:return False
   cmd=[sys.executable,str(P/'run_cell.py'),'--out',str(a.out/name),'--cores',str(cores),'--engines',str(engines),'--pattern',pattern,'--size',str(size),'--batch',str(batch),'--seed',str(20261022+block),'--lock-fd',str(lock.fileno())]
   if kind!='timing':cmd+=['--'+kind]
   begin=time.time()
   with (a.out/(name+'.log')).open('x') as f:
    child=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,pass_fds=(lock.fileno(),));save('running',dict(name=name,pid=child.pid,command=cmd));rc=child.wait()
   rec=dict(name=name,kind=kind,block=block,returncode=rc,wall_s=time.time()-begin,command=cmd);records.append(rec)
   assert rc==0,name
   summary=json.loads((a.out/name/'summary.json').read_text());assert summary['status']=='pass';rec['status']='pass';save('running');return True
  for i,(cores,engines,pattern,size,batch) in enumerate([(1,1,'random',64,1),(110,2,'random',16384,32),(110,2,'contiguous',16384,32)]):
   assert run('fixture-'+str(i),cores,engines,pattern,size,batch,kind='fixture'),'budget before fixtures'
  plan=[]
  for block in range(3):
   cells=[(c,e,p,s,b) for c,e,p in REGIMES for s in SIZES for b in BATCHES];random.Random(20261022+block).shuffle(cells)
   plan += [dict(block=block,cores=c,engines=e,pattern=p,size=s,batch=b,name=f'b{block}-c{c}-e{e}-{p}-s{s}-b{b}') for c,e,p,s,b in cells]
  write(a.out/'planned-cells.json',plan)
  for block in range(3):
   if not run(f'calibration-{block}',1,1,'random',64,1,block,kind='calibration'):break
   if block==0:
    estimate=max(statistics.median(r['wall_s'] for r in records[1:3]),records[-1]['wall_s'])*486*1.2
    write(a.out/'budget-estimate.json',dict(estimated_grid_wall_s=estimate,remaining_s=deadline-time.monotonic(),not_a_measurement_result=True))
    if estimate>deadline-time.monotonic():
     write(a.out/'not-measured.json',[dict(**c,status='not_measured_time_limit') for c in plan]);save('budget_infeasible');return
   for cell in [c for c in plan if c['block']==block]:
    if not run(cell['name'],cell['cores'],cell['engines'],cell['pattern'],cell['size'],cell['batch'],block):
     done={r['name'] for r in records};write(a.out/'not-measured.json',[dict(**c,status='not_measured_time_limit') for c in plan if c['name'] not in done]);save('time_limit');return
  done={r['name'] for r in records};missing=[c for c in plan if c['name'] not in done]
  if missing:write(a.out/'not-measured.json',[dict(**c,status='not_measured_time_limit') for c in missing]);save('time_limit')
  else:save('complete')
 except BaseException as exc:
  save('failed');write(a.out/'failure.json',dict(error=repr(exc)));raise
 finally:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
if __name__=='__main__':main()
