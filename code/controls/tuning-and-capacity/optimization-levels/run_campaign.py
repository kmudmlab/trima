#!/usr/bin/env python3
import json,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parent
commands=[
 ['run_specialized.py','--suite','tot','--out','tot-study'],
 ['run_specialized.py','--suite','trust','--out','trust-study'],
 ['run_specialized.py','--suite','wetric','--out','wetric-tuning'],
 ['run_followup.py','--out','confirmation','--graphs','comlj,orkut,hollywood,stanford','--blocks','3','--selected'],
 ['run_specialized.py','--suite','btc','--out','btc-ablation'],
]
records=[]
for cmd in commands:
    print('SUITE',cmd,flush=True);rc=subprocess.run([sys.executable,str(R/cmd[0]),*cmd[1:]]).returncode
    records.append(dict(command=cmd,returncode=rc));(R/'campaign-status.json').write_text(json.dumps(records,indent=2)+'\n')
    if rc:raise SystemExit(rc)
