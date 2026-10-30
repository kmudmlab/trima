#!/usr/bin/env python3
"""승인된 WebCC 생략 정책. timing 수치를 stdout/요약 문서에 공개하지 않는다."""
import argparse,json,os,subprocess,sys,time,traceback
from pathlib import Path
HERE=Path(__file__).resolve().parent
E=HERE.parents[2]
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
args.out.mkdir(parents=True,exist_ok=False);records=[]
def save(status,active=None):
    path=args.out/'status.json';tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(status=status,pid=os.getpid(),active=active,records=records),indent=2)+'\n');tmp.replace(path)
meta=json.loads((E/'cpu-validation/clique140.json').read_text())
jobs=[('post-interrupt-fixture',[sys.executable,str(HERE/'code/direct/run_port.py'),'--input',str(E/'cpu-validation/clique140.csr'),'--expected',str(meta['count']),'--out',str(args.out/'device-fixture'),'--mode','steptc-direct','--opt-level','2','--cores','1','--cpu-check','--counters','1','--reps','1'])]
for kind in ['direct','source']:
    jobs.append((kind,[sys.executable,str(HERE/f'{kind}_campaign_v2.py'),'--phase','graph','--graph','webcc','--out',str(HERE/f'webcc-{kind}-continue-v2')]))
try:
    for name,cmd in jobs:
        with (args.out/f'{name}.log').open('x') as log:
            child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
            save('running',dict(name=name,pid=child.pid,command=cmd,started_unix=time.time()))
            rc=child.wait()
        record=dict(name=name,command=cmd,returncode=rc,finished_unix=time.time());records.append(record)
        # Persist child returncode before any progress notification.
        with (args.out/'child-exits.jsonl').open('a') as journal:
            journal.write(json.dumps(record)+'\n');journal.flush();os.fsync(journal.fileno())
        save('failed' if rc else 'running')
        if rc:raise RuntimeError(name)
        with (args.out/'progress.log').open('a') as progress:print('PASS',name,file=progress,flush=True)
    save('complete_with_time_limits')
except BaseException as exc:
    save('failed')
    (args.out/'failure.json').write_text(json.dumps(dict(error=repr(exc),traceback=traceback.format_exc(),records=records),indent=2)+'\n')
    raise
