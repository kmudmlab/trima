#!/usr/bin/env python3
import datetime,json,os,subprocess,sys,time,traceback
from pathlib import Path
G=Path(__file__).resolve().parent.parent
D=G/'order-dependence'
O=G/'order-dependence-original-v2'
STATE=D/'original-followup-status.json'
def now():return datetime.datetime.now().astimezone().isoformat()
def save(d):
 p=STATE.with_suffix('.tmp');p.write_text(json.dumps(d,indent=2)+'\n');p.replace(STATE)
def alive(pid):
 p=Path('/proc')/str(pid)/'stat'
 if not p.exists():return False
 try:return p.read_text().split(') ',1)[1].split()[0] not in ('Z','X')
 except FileNotFoundError:return False
state=dict(status='waiting',pid=os.getpid(),started_at=now(),wait_for_campaign_pid=2248835)
assert not STATE.exists() and not O.exists()
save(state)
try:
 while True:
  d=json.loads((G/'order-dependence-v1/status.json').read_text())
  assert d['pid']==2248835
  if not alive(2248835):
   assert d['status']=='complete',('preceding campaign did not pass',d.get('error'))
   break
  time.sleep(5)
 state.update(status='starting_original',original_started_at=now());save(state)
 with (D/'original-v2.log').open('x') as log:
  p=subprocess.Popen([sys.executable,str(D/'campaign_original.py'),'--out',str(O)],stdout=log,stderr=subprocess.STDOUT)
  state.update(status='running_original',child_pid=p.pid);save(state);rc=p.wait()
 state.update(status='complete' if rc==0 else 'failed',returncode=rc,finished_at=now());save(state)
 sys.exit(rc)
except Exception as e:
 state.update(status='failed',error=repr(e),traceback=traceback.format_exc(),finished_at=now());save(state);raise
