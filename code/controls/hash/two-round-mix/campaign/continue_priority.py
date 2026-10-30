#!/usr/bin/env python3
"""WebCC 종료·안전한 waiter 교체 뒤에만 시작하는 우선순위 체인."""
import argparse,fcntl,json,os,subprocess,sys,time
from pathlib import Path
H=Path(__file__).resolve().parent;G=H.parent;S=G/'suite-v1';R=G/'trima-supply-v1'
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
a.out.mkdir(parents=True,exist_ok=False);records=[]
guard=(R/'downstream.lock').open('a');fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
queue_guard=(H/'priority-queue.lock').open('a');fcntl.flock(queue_guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
queue=['WebCC completed','TriMA hash0/1','Task13 train/freeze/notify/validation','port hash controls','Polak profile','STOP: Claude prediction record','Task14 profile','STOP: Claude prediction record']
def save(status,active=None):
 p=a.out/'status.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(dict(status=status,pid=os.getpid(),active=active,records=records,queue=queue,updated_unix=time.time()),indent=2)+'\n');t.replace(p)
def execute(name,cmd):
 with (a.out/(name+'.log')).open('x') as f:
  p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT);save('running',dict(name=name,pid=p.pid,command=cmd));rc=p.wait()
 records.append(dict(name=name,command=cmd,returncode=rc));assert rc==0,name;save('running')
try:
 assert json.loads((S/'webcc-resume-v2/status.json').read_text())['status'] in ('complete','complete_with_time_limits')
 assert json.loads((H/'cpu-v1/summary.json').read_text())['status']=='pass'
 assert json.loads((H/'cpu-graphs-v1/summary.json').read_text())['status']=='pass'
 with (G.parent/'hardware.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  owner=subprocess.run(['fuser','/dev/tenstorrent/0'],capture_output=True,text=True)
  assert owner.returncode==1 and not owner.stdout.strip()
  execute('reuse-cpu-preparation',[sys.executable,str(H/'collect_cpu.py'),'--out',str(H/'cpu-graphs-v1')])
 execute('device-fixtures',[sys.executable,str(H/'campaign.py'),'--phase','fixtures','--out',str(a.out/'device-fixtures-v1')])
 graphs=[g['graph'] for g in json.loads((S/'preflight.json').read_text())['graphs']]
 (a.out/'trima').mkdir()
 for g in graphs:execute('trima-'+g,[sys.executable,str(H/'campaign.py'),'--phase','trima','--graph',g,'--out',str(a.out/'trima'/g)])
 execute('task13',[sys.executable,str(G/'trima-supply/campaign.py'),'--hash-root',str(a.out),'--out',str(R/'campaign-priority-v2')])
 assert (R/'FROZEN.md').exists() and (R/'FREEZE_NOTIFICATION.json').exists()
 (a.out/'ports').mkdir()
 for g in graphs:execute('ports-'+g,[sys.executable,str(H/'campaign.py'),'--phase','ports','--graph',g,'--out',str(a.out/'ports'/g)])
 execute('hash-analysis',[sys.executable,str(H/'summarize.py'),'--root',str(a.out),'--out',str(H/'analysis-priority-v2')])
 execute('polak-profile',[sys.executable,str(G/'polak/profile_campaign.py'),'--out',str(G/'polak-v1/profile-v1')])
 assert json.loads((G/'polak-v1/profile-v1/status.json').read_text())['status']=='profiles_complete_awaiting_prediction'
 (a.out/'TASK14_PENDING.json').write_text(json.dumps(dict(status='pending_Polak_prediction_gate',spec='TASK14_LOCALITY.md',next_phase='Task14 profile only; stop again for prediction',automatic_timing=False),indent=2)+'\n')
 save('stopped_for_Claude_predictions_task14_profile_pending')
except BaseException:
 save('failed');raise
