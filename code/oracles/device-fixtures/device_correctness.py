from pathlib import Path
import json,hashlib,fcntl,subprocess,sys,os,traceback
import numpy as np
P=Path(__file__).resolve().parent
read=lambda f:json.loads(f.read_text());sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
def write(f,x):
 t=f.with_suffix('.tmp');t.write_text(json.dumps(x,indent=2)+'\n');t.replace(f)
def main():
 O=P/'correctness-new-v1';O.mkdir();records=[];active=None
 with (P/'campaign.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  order=read(P/'DEVICE_ORDER.json')
  def state(s):write(O/'status.json',dict(status=s,pid=os.getpid(),planned=len(order),passed=len(records),active=active,timing_started=False))
  try:
   assert read(P/'cpu-new-fixtures-v2/COMPLETE.json')['checks']==222
   assert read(P/'replay-composition-v1/COMPLETE.json')['graph_configs']==85
   assert read(P/'reuse-audit-v1/COMPLETE.json')['status']=='pass'
   assert read(P/'PROTOCOL_REGRESSION.json')['schedules']==216
   frozen=read(P/'SOURCE_FROZEN.json');jobs={j['graph']:j for j in read(P/'jobs-ready.json')};settings=read(P/'prior-FINAL_SETTINGS.json')
   write(O/'ORDER.json',order)
   for item in order:
    for f,h in frozen.items():assert sha(P/f)==h,f
    g=item['graph'];v=item['variant'];j=jobs[g];profile=item['profile'];launches=item['launches'];isB=v in ['L5-T','L5-H']
    name=item['name'];dst=O/name;active=dict(item);state('running')
    common=['--input',j['tt_input'],'--out',str(dst),'--expected',str(j['expected_count']),'--engine-counts',str(P/'input-metadata'/f'{g}.json'),'--chunk-kib','262144','--reps','1','--profile' if profile else '--validate-off','--launches',str(launches)]
    if not isB:
     base=list(settings['cli_base']);base[base.index('--hash-mix')+1]=str({'mix0':0,'mix1':1}.get(v,2))
     cmd=[sys.executable,str(P/'code/trima/correctness.py'),*common,*base,'--stage',v,'--aux-rowptr','0','--tail-merge',str(int(v!='T-off')),'--pipe-meta','0','--merge-bytes',str(j['merge_bytes']),'--no-trisc','0','--serialize-sources',str(int(v=='L6')),'--validated-sha',j['input_sha256']]
    else:
     cmd=[sys.executable,str(P/'code/trust/profile.py'),*common,'--prune','1','--hash-oa','1','--hash-mix','2','--direct','1','--lookup-width','4','--page-bytes','16384','--row-cache-kib','16','--col-cache-kib','64','--arena-kib','64','--meta-stage','64','--hash-size','16384','--hash-pool',str(int(v=='L5-H')),'--merge-bytes',str(j['merge_bytes'])]
    write(O/'active-command.json',dict(command=cmd,cell=active))
    with (O/(name+'.log')).open('x') as log:
     child=subprocess.Popen(cmd,stdout=log,stderr=log);active['pid']=child.pid;state('running');rc=child.wait()
    assert rc==0,('device failure',name,rc)
    x=read(P/('reference-expected' if v in ['L6','L7'] else 'expected')/f'{g}-{v}.json');comparisons=[]
    for rep in range(launches):
     a=np.load(dst/(f'result-{rep}.npy' if isB else f'raw-{rep}.npy'));val=lambda r,k:int(r[k])+(int(r[k+1])<<32)
     counts=[val(r,0) for r in a]
     cores=[counts[c*2]+counts[c*2+1] for c in range(110)] if isB else counts
     assert cores==x['counts110'],('count',name,rep)
     got=None
     if profile:
      got=[[val(r,k) for k in ([32,34,36,38,40,4] if isB else [40,42,44,46,48,60])] for r in a]
      assert got==x['engine220' if isB else 'core110'],('QBW/candidates',name,rep)
     comparisons.append(dict(repeat=rep,count_exact=True,candidates_QBW_exact=True if profile else 'counters_off',observed=got,counts110=cores))
    cfg=read(dst/'config.json');cb=read(dst/'cb-allocation-0.json');plan=next(r for r in read(P/'CB_PLAN.json') if r['graph']==g and r['variant']==v)
    assert cb['total_cb_bytes']==cfg['l1_bytes']==plan['CB_bytes']<=1392*1024,('CB',name,cb,cfg['l1_bytes'],plan)
    assert read(dst/'summary.json')['timing_measured']==False
    write(dst/'COMPARISON.json',dict(status='pass',comparisons=comparisons,CB_exact=True,expected_sha256=sha(P/('reference-expected' if v in ['L6','L7'] else 'expected')/f'{g}-{v}.json')))
    records.append(dict(**item,status='pass',CB_bytes=cb['total_cb_bytes'],comparison_sha256=sha(dst/'COMPARISON.json'),summary_sha256=sha(dst/'summary.json')));active=None;state('running')
   write(O/'COMPLETE.json',dict(status='pass',passed=len(order),failed=0,records=records,timing_started=False));state('complete')
  except BaseException as e:
   write(O/'FAILURE.json',dict(error=repr(e),active=active,records=records,traceback=traceback.format_exc()));state('failed');raise
if __name__=='__main__':main()
