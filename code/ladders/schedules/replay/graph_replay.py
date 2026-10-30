from pathlib import Path
import subprocess,json,hashlib,os,traceback,concurrent.futures,threading,resource
P=Path(__file__).resolve().parent;O=P/'graph-replay-v2';read=lambda f:json.loads(f.read_text());lock=threading.Lock();stop=threading.Event();records=[]
def sha(f):
 h=hashlib.sha256()
 with f.open('rb') as x:
  for b in iter(lambda:x.read(16<<20),b''):h.update(b)
 return h.hexdigest()
def write(p,x):
 tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,indent=2)+'\n');tmp.replace(p)
def safe():
 r=subprocess.run(['nvidia-smi','--query-compute-apps=pid,process_name','--format=csv,noheader'],capture_output=True,text=True)
 assert r.returncode==0 and not r.stdout.strip(),('GPU compute appeared; no new CPU work',r.stdout)
 r=subprocess.run(['ps','-eo','user=,pcpu=,args='],capture_output=True,text=True)
 heavy=[x for x in r.stdout.splitlines() if len(x.split(None,2))==3 and x.split()[0] not in ['hmpark','root'] and float(x.split()[1])>50]
 assert not heavy,('other user heavy CPU',heavy)
def run(cmd,log):
 with log.open('x') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
 assert r.returncode==0,('CPU replay subprocess',cmd,r.returncode)
def one(j,family):
 g=j['graph'];fid=dict(steptc=1,wetric=2,tricore=3)[family];dst=O/g/family;dst.mkdir(parents=True);old=P/'prior-graph-replay'/g;man=read(old/(family+'-manifest.json'));inp=Path(j['bear_input']);sch=dst/'schedule.bin'
 with lock:
  if stop.is_set():return
  safe()
 run([str(P/'prepare'),str(inp),str(sch),str(fid+6),'0'],dst/'prepare.log')
 assert sha(sch)==man['schedule_sha256'],('schedule SHA',g,family)
 write(dst/'manifest.json',dict(man,input_path=str(inp),schedule_path=str(sch),endpoint_array_created=False))
 for supply,d in [('cache',0),('range',1)]:
  for variant,t,ctx in [('D-end',0,1),('plus-T',1,1)]+([('plus-context',1,2)] if family=='steptc' else []):
   if stop.is_set():return
   with lock:safe()
   target=dst/(supply+'-'+variant+'.json');prior=read(old/(family+'-'+supply+'.json'))
   if g=='friendster' and supply=='cache' and family in ['steptc','tricore']:
    write(target,dict(status='refused_capacity',reason='unchanged task22/task28 kernel configuration buffer capacity',variant=variant));rec=dict(graph=g,family=family,supply=supply,variant=variant,status='refused_capacity')
   else:
    binary=P/'host-bin-io'/f'io-t{t}-f{fid}-d{d}{"-ctx2" if ctx==2 else ""}'
    run([str(binary),str(inp),str(sch),'220',str(target)],target.with_suffix('.log'))
    got=read(target)['engines'];want=prior['engines'];assert len(got)==len(want)==220
    assert [x[1:4] for x in got]==[x[1:4] for x in want],('candidate identity',g,family,supply,variant)
    cols=list(range(4,11)) if (t and (ctx==1 or d)) else ([5,6,8,9] if ctx==1 else [])
    assert [[x[k] for k in cols] for x in got]==[[x[k] for k in cols] for x in want],('unchanged IO',g,family,supply,variant)
    rec=dict(graph=g,family=family,supply=supply,variant=variant,status='pass',physical_QBW_exact=True,prior_sha256=sha(old/(family+'-'+supply+'.json')),replay_sha256=sha(target),binary_sha256=sha(binary))
   with lock:
    records.append(rec);write(O/'status.json',dict(status='running',records=records,passed=sum(x['status']=='pass' for x in records),refused=sum(x['status']=='refused_capacity' for x in records)));print(g,family,supply,variant,rec['status'],flush=True)
def main():
 O.mkdir();resource.setrlimit(resource.RLIMIT_AS,(28<<30,28<<30))
 try:
  jobs=read(P/'jobs-28a.json')
  # Hash each input once, before schedules; at most two single-threaded workers.
  for j in jobs:
   safe();assert sha(Path(j['bear_input']))==j['input_sha256'],('input SHA',j['graph'])
  write(O/'INPUT_SHA_VERIFIED.json',{j['graph']:j['input_sha256'] for j in jobs})
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   pending={};items=iter([(j,f) for j in jobs for f in ['steptc','wetric','tricore']])
   for _ in range(2):
    x=next(items,None)
    if x:pending[pool.submit(one,*x)]=x
   while pending:
    done,_=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
    for f in done:
     pending.pop(f)
     try:f.result()
     except BaseException:stop.set();raise
     x=next(items,None)
     if x:pending[pool.submit(one,*x)]=x
  assert len(records)==224 and sum(x['status']=='pass' for x in records)==219
  write(O/'COMPLETE.json',dict(status='pass',records=records,passed=219,refused=5,device_used=False,timing_started=False));write(O/'status.json',dict(status='complete',passed=219,refused=5))
 except BaseException as e:
  stop.set();write(O/'FAILURE.json',dict(error=repr(e),records=records,traceback=traceback.format_exc()));write(O/'status.json',dict(status='failed',records=records));raise
if __name__=='__main__':main()
