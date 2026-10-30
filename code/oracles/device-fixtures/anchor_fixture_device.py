from pathlib import Path
import json,hashlib,fcntl,subprocess,sys,os,traceback
P=Path(__file__).resolve().parent
read=lambda f:json.loads(f.read_text());sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
def write(f,x):f.write_text(json.dumps(x,indent=2)+'\n')
def main():
 O=P/'anchor-fixture-device-v1';O.mkdir();records=[];active=None
 with (P/'campaign.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  def state(s):write(O/'status.json',dict(status=s,passed=len(records),planned=18,active=active,pid=os.getpid(),timing_started=False))
  try:
   assert read(P/'correctness-new-v1/COMPLETE.json')['status']=='pass'
   assert read(P/'anchor-fixture-prepared-v2/COMPLETE.json')['cells']==9
   frozen=read(P/'ANCHOR_FIXTURE_SOURCE_FROZEN.json');jobs={j['graph']:j for j in read(P/'jobs-ready.json')};settings=read(P/'ANCHOR_FIXTURE_SETTINGS.json')['anchors']
   for g in ['clique140','long-collision-boundary','random12']:
    for family in ['steptc','wetric','tricore']:
     j=jobs[g];root=P/'anchor-fixture-prepared-v2'/f'{family}-{g}';m=read(root/'manifest.json')
     for counters in [1,0]:
      for f,h in frozen.items():assert sha(P/f)==h,f
      name=f'{g}-{family}-c{counters}';dst=O/name;active=dict(name=name,graph=g,family=family,counters=counters);state('running')
      cmd=[sys.executable,str(P/'anchor-fixture-code/profile.py'),'--input',j['tt_input'],'--out',str(dst),'--expected',str(j['expected_count']),'--validated-sha',j['input_sha256'],'--schedule',str(root/'schedule.bin'),'--schedule-sha',m['schedule_sha256'],'--prepare-manifest',str(root/'manifest.json'),'--replay',str(root/'replay.json'),'--counters',str(counters),'--reps','1']
      for k,v in settings[family]['options'].items():cmd+=['--'+k.replace('_','-'),str(v)]
      write(O/'active-command.json',dict(command=cmd))
      with (O/(name+'.log')).open('x') as log:
       child=subprocess.Popen(cmd,stdout=log,stderr=log);active['pid']=child.pid;state('running');rc=child.wait()
      assert rc==0,('device failure',name,rc)
      s=read(dst/'summary.json');assert s['status']=='pass' and s['per_owner_exact'] and not s['timing_measured']
      cb=read(dst/'cb-allocation.json');assert cb['total_cb_bytes']==s['l1_bytes']<=1392*1024
      records.append(dict(**active,status='pass',summary_sha256=sha(dst/'summary.json'),comparison_sha256=sha(dst/'CPU_DEVICE_COMPARISON.json'),CB_bytes=cb['total_cb_bytes']));active=None;state('running')
   write(O/'COMPLETE.json',dict(status='pass',passed=18,failed=0,records=records,timing_started=False));state('complete')
  except BaseException as e:
   write(O/'FAILURE.json',dict(error=repr(e),records=records,active=active,traceback=traceback.format_exc()));state('failed');raise
if __name__=='__main__':main()
