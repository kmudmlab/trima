#!/usr/bin/env python3
"""Sequential graphs, one foreground Python child at a time; no pgrep waiter."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;GAP=HERE.parent
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--jobs',required=True)
args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=False);records=[]
def save(status,active=None):
    (args.out/'status.json').write_text(json.dumps(dict(status=status,pid=os.getpid(),active=active,records=records),indent=2)+'\n')
for spec in args.jobs.split(','):
    task,graph=spec.split(':');assert task in ['trisc','direct','source']
    runner=GAP/'trisc/campaign.py' if task=='trisc' else HERE/('direct_campaign.py' if task=='direct' else 'source_campaign.py')
    dst=(GAP/'trisc-v1' if task=='trisc' else HERE)/f'{graph}-{task}-continue-v1'
    cmd=[sys.executable,str(runner),'--phase','graph','--graph',graph,'--out',str(dst)]
    print('START',spec,flush=True);start=time.time()
    with (args.out/f'{task}-{graph}.log').open('x') as log:
        process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
        save('running',dict(job=spec,pid=process.pid,command=cmd,started_unix=start))
        rc=process.wait()
    records.append(dict(job=spec,command=cmd,returncode=rc,wall_s=time.time()-start,result_dir=str(dst)))
    if rc:save('failed');raise RuntimeError(spec)
    save('running');print('PASS',spec,flush=True)
save('complete')
