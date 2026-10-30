"""Mac-only sequential full-input Q/B/W replay. No endpoint arrays or timing."""
import hashlib,json,os,shutil,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parent;G=P.parent
read=lambda p:json.loads(p.read_text())
def write(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,indent=2)+'\n');t.replace(p)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(16<<20),b''):h.update(chunk)
 return h.hexdigest()
def main():
 assert os.uname().sysname=='Darwin','CPU replay must not run on TT'
 assert read(P/'cpu-fixtures-v2/COMPLETE.json')['checks']==666
 assert read(P/'cpu-io-check-v1/COMPLETE.json')['checks']==666
 out=P/'cpu-graphs-v1';out.mkdir(exist_ok=False);records=[]
 def state(status,active=None):write(out/'status.json',dict(status=status,pid=os.getpid(),active=active,passed=len(records),records=records,timing_started=False))
 try:
  for job in read(P/'jobs-28a.json'):
   g=job['graph'];dst=out/g;dst.mkdir()
   with tempfile.TemporaryDirectory(prefix='task28-'+g+'-',dir='/private/tmp') as tmp:
    temp=Path(tmp)
    if g.startswith('roadNet'):inp=G/'locality-v1/inputs-v1'/f'{g}.csr'
    else:
     inp=temp/'input.csr';state('running',dict(graph=g,phase='read_input_to_mac'))
     # Read-only transfer; no compilation, replay, or CPU traversal on bear.
     subprocess.run(['rsync','-a','--',f"bear:{job['bear_input']}",str(inp)],check=True,stdout=subprocess.DEVNULL)
    digest=sha(inp);assert digest==job['input_sha256'],('input SHA',g)
    for family,f in [('steptc',1),('wetric',2),('tricore',3)]:
     schedule=temp/f'{family}-schedule.bin';state('running',dict(graph=g,family=family,phase='mac_schedule'))
     result=subprocess.run([str(P/'host-bin/prepare-schedule'),str(inp),str(schedule),str(f+6),'0'],capture_output=True,text=True)
     (dst/f'{family}-prepare.stdout').write_text(result.stdout);(dst/f'{family}-prepare.stderr').write_text(result.stderr)
     assert result.returncode==0,('schedule',g,family,result.stderr)
     info=json.loads(result.stdout);digest_schedule=sha(schedule)
     prior=G/'task22-v1'/family/('prepared-large' if g=='friendster' else 'prepared')/g/'manifest.json'
     if prior.exists():assert digest_schedule==read(prior)['aux_sha256'],('schedule SHA',g,family)
     write(dst/f'{family}-manifest.json',dict(status='pass',input_sha256=digest,schedule_sha256=digest_schedule,schedule_bytes=schedule.stat().st_size,info=info,endpoint_array_created=False))
     for direct in [0,1]:
      name=f'{family}-'+('range' if direct else 'cache');target=dst/f'{name}.json'
      state('running',dict(graph=g,family=family,supply=name,phase='mac_replay'))
      result=subprocess.run([str(P/'host-bin'/f'io-f{f}-d{direct}'),str(inp),str(schedule),'220',str(target)],capture_output=True,text=True)
      target.with_suffix('.stderr').write_text(result.stderr)
      assert result.returncode==0,('replay',g,family,direct,result.stderr)
      x=read(target);assert len(x['engines'])==220
      identity=prior.parent/'identity-e220.json'
      if identity.exists():
       wanted=read(identity)['engines'];assert [r[1:4] for r in x['engines']]==wanted,('candidate identity',g,family,direct)
      records.append(dict(graph=g,family=family,direct=direct,status='pass',result=str(target.relative_to(P)),sha256=sha(target),input_sha256=digest,schedule_sha256=digest_schedule,all_engines=220))
      state('running')
     # Only this campaign's disposable schedule is removed. Old raw data is untouched.
     schedule.unlink()
  write(out/'COMPLETE.json',dict(status='pass',cells=len(records),graphs=16,records=records,timing_started=False));state('complete')
 except BaseException as exc:
  write(out/'FAILURE.json',dict(error=repr(exc),passed=len(records)));state('failed');raise
if __name__=='__main__':main()
