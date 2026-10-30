"""Task43: unchanged author adapters, sm75, GTX1660 only; no TT runtime imports."""
from pathlib import Path
import json,hashlib,subprocess,os,socket,time,datetime,random,statistics,math,csv,traceback,fcntl,xml.etree.ElementTree as ET
P=Path(__file__).resolve().parent
F=['trust','tricore','wetric','steptc']
rd=lambda p:json.loads(p.read_text())
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(16<<20),b''):h.update(b)
 return h.hexdigest()
def wr(p,d):
 t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n');t.replace(p)
def snapshot(dst,phase):
 text=subprocess.check_output(['nvidia-smi'],text=True);xml=subprocess.check_output(['nvidia-smi','-q','-x'],text=True)
 (dst/f'nvidia-smi-{phase}.txt').write_text(text);(dst/f'nvidia-smi-{phase}.xml').write_text(xml)
 tree=ET.fromstring(xml);devices=[];processes=[]
 for gpu in tree.findall('gpu'):
  dev=dict(name=gpu.findtext('product_name'),uuid=gpu.findtext('uuid'),memory={c.tag:c.text for c in gpu.find('fb_memory_usage')},utilization={c.tag:c.text for c in gpu.find('utilization')})
  devices.append(dev)
  for p in gpu.findall('./processes/process_info'):
   pid=p.findtext('pid');owner=subprocess.run(['ps','-p',pid,'-o','user='],capture_output=True,text=True).stdout.strip()
   processes.append(dict(pid=pid,user=owner,name=p.findtext('process_name'),type=p.findtext('type'),used_memory=p.findtext('used_memory')))
 data=dict(utc=now(),devices=devices,processes=processes,contention_observed=bool(processes),scope='before/after only; no process changes')
 wr(dst/f'gpu-state-{phase}.json',data);return data

def main():
 assert socket.gethostname()=='dmlab-desktop';assert os.getpriority(os.PRIO_PROCESS,0)>=10
 assert os.environ.get('CUDA_VISIBLE_DEVICES')=='0'
 with (P/'RUN_STARTED.json').open('x') as f:json.dump(dict(pid=os.getpid(),utc=now(),nice=os.getpriority(os.PRIO_PROCESS,0)),f)
 records=[];exceptions={};active=None;start=now();clock=time.monotonic()
 def state(status):wr(P/'status.json',dict(status=status,pid=os.getpid(),active=active,verification_passed=sum(r['phase']=='verification' and r['status']=='pass' for r in records),timing_passed=sum(r['phase']=='timing' and r['status']=='pass' for r in records),refused=sum(r['status']=='not_applicable_capacity' for r in records),planned_verification=60,planned_timing=180,started_utc=start,updated_utc=now()))
 try:
  with (P.parent/'gpu-gtx1660.lock').open('a') as lock:
   state('waiting_for_gpu_lock');fcntl.flock(lock,fcntl.LOCK_EX)
   init=snapshot(P,'initial');assert len(init['devices'])==1 and 'GTX 1660' in init['devices'][0]['name']
   total=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.total','--format=csv,noheader,nounits'],text=True).strip())*1024**2
   assert total==6144*1024**2
   graphs=rd(P/'inputs.json');bins=rd(P/'binary-manifest.json');assert len(graphs)==15
   for fam,b in bins.items():
    b['local_path']=str(P/b['relative_path']);assert sha(b['local_path'])==b['sha256']
   for g in graphs:assert sha(g['input_path'])==g['input_sha256'],('input SHA mismatch',g['graph'])
   wr(P/'INPUTS_VERIFIED.json',dict(status='pass',graphs=graphs,utc=now(),source_manifest_sha256=sha(P/'source-manifest.json')))
   capacity=[]
   for g in graphs:
    n,m=g['n'],g['m']
    # Same necessary lower bounds as gpu-ranking-v3, not a sufficiency claim.
    req={'trust':24*(n+1)+4*m+1024*1024*100*4+20,'tricore':8*(n+1)+4*m+16777216*8+2048,'wetric':12*(n+1)+4*m+8192*8191//16+8,'steptc':12*m+12*(n+1)}
    for fam,q in req.items():
     item=dict(graph=g['graph'],family=fam,necessary_device_bytes=q,total_device_bytes=total,lower_bound_only=True);capacity.append(item)
     if q>total:exceptions[g['graph']+'/'+fam]=dict(reason='necessary allocation exceeds device capacity',**item)
   wr(P/'CAPACITY_PREFLIGHT.json',capacity)
   order=[]
   for block in range(3):
    cells=[dict(graph=g['graph'],family=fam) for g in graphs for fam in F];random.Random(20261022+block).shuffle(cells);order.append(dict(block=block,seed=20261022+block,cells=cells))
   wr(P/'ORDER.json',order)
   def run(phase,g,fam,block=None,index=None):
    nonlocal active
    name=f'verify-{g["graph"]}-{fam}' if phase=='verification' else f'block{block}-{g["graph"]}-{fam}'
    dst=P/('verification' if phase=='verification' else 'timing')/name;dst.mkdir(parents=True,exist_ok=False)
    key=g['graph']+'/'+fam
    cmd=[bins[fam]['local_path']]
    if fam=='wetric':cmd+=['run',g['input_path'],'10','8192','3',str(g['expected_count'])]
    else:cmd+=[g['input_path'],str(g['expected_count'])]+([] if fam=='steptc' else ['3'])
    active=dict(name=name,phase=phase,graph=g['graph'],family=fam,block=block,index=index,command=cmd);state('running')
    record=dict(phase=phase,graph=g['graph'],family=fam,block=block,index=index,summary=str((dst/'summary.json').relative_to(P)))
    if key in exceptions:
     result=dict(**record,status='not_applicable_capacity',reason=exceptions[key]);wr(dst/'summary.json',result)
    else:
     assert sha(bins[fam]['local_path'])==bins[fam]['sha256']
     before=snapshot(dst,'before');t=time.monotonic();started=now()
     wr(dst/'COMMAND.json',dict(command=cmd,binary_sha256=bins[fam]['sha256'],input_sha256=g['input_sha256'],nice=os.getpriority(os.PRIO_PROCESS,0),protocol='fresh process, warmup1+3, resident_s, no counters',block=block,index=index))
     with (dst/'stdout.log').open('x') as log:
      child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT);active['child_pid']=child.pid;active['started_utc']=started;state('running');rc=child.wait()
     wall=time.monotonic()-t;after=snapshot(dst,'after');output=(dst/'stdout.log').read_text();samples=[]
     for line in output.splitlines():
      try:x=json.loads(line)
      except json.JSONDecodeError:continue
      if x.get('kind')=='sample':samples.append(x)
     # Even a partial output with wrong counts is a semantic failure, never capacity refusal.
     assert all(x['count']==g['expected_count'] for x in samples),('count mismatch',name)
     common=dict(**record,command=cmd,returncode=rc,started_utc=started,finished_utc=now(),wall_s=wall,expected_count=g['expected_count'],input_sha256=g['input_sha256'],binary_sha256=bins[fam]['sha256'],contention_before=before['contention_observed'],contention_after=after['contention_observed'],contention_observed=before['contention_observed'] or after['contention_observed'])
     if rc and ('out of memory' in output.lower() or 'memory allocation' in output.lower()):
      exceptions[key]=dict(reason='CUDA allocation failed',stdout=str((dst/'stdout.log').relative_to(P)),returncode=rc)
      result=dict(**common,status='not_applicable_capacity',reason=exceptions[key]);wr(dst/'summary.json',result)
     else:
      assert rc==0,(name,rc)
      assert len(samples)==4 and samples[0]['warmup'] and not any(x['warmup'] for x in samples[1:]),('sample protocol',name)
      if fam=='wetric':assert all(x['spread']==10 and x['adjacency']==8192 for x in samples)
      vals=[x['resident_s'] for x in samples[1:]];assert all(math.isfinite(v) and v>0 for v in vals)
      result=dict(**common,status='pass',samples=samples,count_exact=True,median_s=statistics.median(vals),timing='gpu-ranking-v3 unchanged resident_s; Count launch/synchronization/reduction/readback, uploads excluded; TriCore chunk sum')
      wr(dst/'summary.json',result)
    records.append(dict(**record,status=result['status'],median_s=result.get('median_s'),contention_observed=result.get('contention_observed'),summary_sha256=sha(dst/'summary.json')))
    wr(P/'RECORDS.json',records);wr(P/'CAPACITY_REFUSALS.json',exceptions);active=None;state('running');print(result['status'],name,flush=True)
   for g in graphs:
    for fam in F:run('verification',g,fam)
   wr(P/'verification/COMPLETE.json',dict(status='complete',records=records.copy(),utc=now()))
   for b in order:
    for i,c in enumerate(b['cells']):run('timing',next(g for g in graphs if g['graph']==c['graph']),c['family'],b['block'],i)
    wr(P/'timing'/f'BLOCK{b["block"]}_COMPLETE.json',dict(status='complete',block=b['block'],utc=now()))
   tt={(r['graph'],r['family']):r for r in rd(P/'TT_FROZEN.json')['rows']};table=[]
   for g in graphs:
    med={}
    for fam in F:
     group=[r for r in records if r['phase']=='timing' and r['graph']==g['graph'] and r['family']==fam];assert len(group)==3
     if g['graph']+'/'+fam not in exceptions:
      assert all(r['status']=='pass' for r in group);med[fam]=statistics.median(r['median_s'] for r in group)
    for fam in F:
     old=tt[(g['graph'],fam)];v=med.get(fam)
     table.append(dict(graph=g['graph'],family=fam,gpu_status='measured' if v is not None else 'not_applicable_capacity',gpu_median_s=v,gpu_rank=1+sum(x<v for x in med.values()) if v is not None else None,**{k:old.get(k) for k in ['tt_variant','tt_median_s','tt_rank','tt_source','tt_scope']}))
   wr(P/'gpu-vs-tt.json',table)
   with (P/'gpu-vs-tt.csv').open('x',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
   with (P/'CONTENTION.csv').open('x',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['phase','graph','family','block','status','contention_observed','summary']);w.writeheader();w.writerows({k:r[k] for k in w.fieldnames} for r in records)
   assert len(records)==240
   complete=dict(status='complete',verification_passed=sum(r['phase']=='verification' and r['status']=='pass' for r in records),timing_passed=sum(r['phase']=='timing' and r['status']=='pass' for r in records),refused_cells=sum(r['status']=='not_applicable_capacity' for r in records),failed=0,capacity_refusals=exceptions,blocks=3,records=records,started_utc=start,completed_utc=now(),elapsed_s=time.monotonic()-clock,table_sha256=sha(P/'gpu-vs-tt.csv'),protocol='fresh process, warmup1+3, seeds 20261022+block, median of block medians, all repetitions count checked',interpretation=False)
   wr(P/'timing/COMPLETE.json',complete);wr(P/'COMPLETE.json',complete);state('complete')
 except BaseException as e:
  wr(P/'FAILURE.json',dict(error=repr(e),traceback=traceback.format_exc(),active=active,records=records,utc=now()));state('failed');raise
if __name__=='__main__':main()
