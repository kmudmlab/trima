from pathlib import Path
import ast,json,hashlib,subprocess,traceback
import numpy as np
P=Path(__file__).resolve().parent;G=Path('experiments/gpu_tt_portability_20261021/optimization_20261022/gap');O=P/'cpu-context-fixtures-v2';read=lambda f:json.loads(f.read_bytes())
def write(f,x):f.write_text(json.dumps(x,indent=2)+'\n')
source=ast.parse((G/'task28-v1/cpu_fixtures_v2.py').read_text());fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='schedule');exec(compile(ast.Module(body=[fn],type_ignores=[]),'schedule','exec'))
def main():
 O.mkdir();records=[];active=None
 try:
  for f in sorted((P/'fixtures').glob('*.csr')):
   for family in [1]:
    dst=O/f.stem/f'f{family}';dst.mkdir(parents=True);sched=dst/'schedule.bin';schedule(f,sched,family)
    for engines in [1,7,220]:
     for direct in [0,1]:
      oldpath=G/'task28-v1/cpu-fixtures-v2'/f.stem/f'f{family}'/f'e{engines}-d{direct}.json';old=read(oldpath)['engines']
      for tail in [1]:
       active=dict(fixture=f.stem,family=family,engines=engines,direct=direct,variant='plus-context')
       target=dst/f'e{engines}-d{direct}-t{tail}.json'
       cmd=[str(P/'host-bin'/f'replay-t{tail}-f{family}-d{direct}-ctx2'),str(f),str(sched),str(engines),str(target)]
       r=subprocess.run(cmd,capture_output=True,text=True);target.with_suffix('.log').write_text(r.stdout+r.stderr);assert r.returncode==0,('CPU replay',active,r.stderr)
       got=read(target)['engines'];assert len(got)==engines
       assert [x[:4] for x in got]==[x[:4] for x in old],('count/candidate/identity',active)
       assert sum(x[0] for x in got)==read(f.with_suffix('.json'))['count']
       cols=list(range(11)) if direct else [0,1,2,3]
       assert [[x[k] for k in cols] for x in got]==[[x[k] for k in cols] for x in old],('unchanged IO',active)
       records.append(dict(**active,status='pass',physical_QBW_exact=True,reference_sha256=hashlib.sha256(oldpath.read_bytes()).hexdigest()))
       write(O/'status.json',dict(status='running',passed=len(records),active=active))
   print(f.stem,len(records),flush=True)
  assert len(records)==222
  write(O/'COMPLETE.json',dict(status='pass',checks=222,records=records,timing_started=False));write(O/'status.json',dict(status='complete',passed=222))
 except BaseException as e:
  write(O/'FAILURE.json',dict(error=repr(e),records=records,active=active,traceback=traceback.format_exc()));write(O/'status.json',dict(status='failed',passed=len(records),active=active));raise
if __name__=='__main__':main()
