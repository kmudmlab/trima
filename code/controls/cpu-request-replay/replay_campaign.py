#!/usr/bin/env python3
"""CPU only: run the unchanged algorithm templates over a software device-IO replay."""
import argparse,hashlib,json,os,socket,subprocess,time
from pathlib import Path
P=Path(__file__).resolve().parent
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(16<<20),b''):h.update(block)
 return h.hexdigest()
def write(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--jobs',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
 assert socket.gethostname() not in ['tt','dmlab-tt'],'CPU replay must not run on TT'
 a.out.mkdir(parents=True,exist_ok=False);records=[];digests={};binaries={};base_vectors={}
 spec=json.loads(a.jobs.read_text())
 if spec.get('kind')=='candidates':
  calibration=json.loads(Path(spec['calibration']).read_text());assert calibration['checks']==36 and calibration['status']=='pass'
 def save(status,active=None):write(a.out/'status.json',dict(status=status,pid=os.getpid(),host=socket.gethostname(),active=active,records=records))
 try:
  for job in spec['jobs']:
   path=Path(job['input']);name=job['name'];dst=a.out/name;dst.mkdir()
   if str(path) not in digests:digests[str(path)]=sha(path)
   assert digests[str(path)]==job['input_sha256'],'Input hash mismatch: '+str(path)
   flags=job.get('compile_flags',[]);key=tuple(flags)
   if key not in binaries:
    binary=(a.out/('replay-'+str(len(binaries)))).resolve()
    cmd=['g++','-O2','-std=c++17',*flags,str(P/'code/prepare.cpp'),'-o',str(binary)]
    subprocess.run(cmd,check=True);binaries[key]=binary
   cmd=[str(binaries[key]),str(path),str(dst/'aux.bin'),str(job['mode']),'0',str(job.get('engines',220))]
   start=time.time()
   with (dst/'stdout.json').open('x') as out,(dst/'stderr.log').open('x') as err:
    child=subprocess.Popen(cmd,stdout=out,stderr=err);save('running',dict(name=name,pid=child.pid,command=cmd,started_unix=start));rc=child.wait()
   assert rc==0,name
   d=json.loads((dst/'stdout.json').read_text());reference=job.get('reference')
   if reference:
    c=reference['counters']
    for field in ['count','engine_counts','engine_candidates','jobs']:assert d[field]==c[field],(name,field)
    wanted=[c['row_pages'],c['col_pages'],c['aux_pages'],*c['range_requests_row_col_aux'],*c['range_bytes_row_col_aux'],c['wait_calls'],c['target_batches'],c['metadata_batches']]
    delta=[x-y for x,y in zip(d['io'],wanted)];status='exact' if not any(delta) else 'approximate'
   else:
    assert d['count']==job['expected_count'],name
    key=(job['graph'],job['family']);vectors=[d[k] for k in ['engine_counts','engine_candidates']]
    if job['variant']=='base':base_vectors[key]=vectors
    else:assert vectors==base_vectors[key],name+' base/D1 candidate or ownership differs'
    wanted=None;delta=None;status='cpu_only_pending_device'
   r=dict(name=name,graph=job['graph'],family=job['family'],variant=job['variant'],status=status,
    io_cpu=d['io'],io_device=wanted,delta=delta,Q_base_cpu=sum(d['io'][:3]),Q_D1_cpu=sum(d['io'][3:6]),
    candidates=sum(d['engine_candidates']),wall_s=time.time()-start,input_sha256=digests[str(path)],command=cmd,reference=reference)
   if reference and 'engine_io' in reference:
    assert d['engine_io']==reference['engine_io'],name+' per-engine IO mismatch'
   write(dst/'comparison.json',r);records.append(r)
   if spec.get('kind')!='candidates':(dst/'aux.bin').unlink()
   else:write(dst/'aux-manifest.json',dict(aux_sha256=sha(dst/'aux.bin'),input_sha256=digests[str(path)],n=d['n'],m=d['m'],maxdegree=d['maxdegree'],aux_words=d['aux_words'],count=d['count'],engine_counts=d['engine_counts'],engine_candidates=d['engine_candidates']))
   save('running');print(r['status'].upper(),name,'delta',delta,flush=True)
  save('complete');write(a.out/'summary.json',dict(status='pass',checks=len(records),exact=sum(r['status']=='exact' for r in records),approximate=sum(r['status']!='exact' for r in records),records=records,
   source_sha256={str(p.relative_to(P)):sha(p) for p in (P/'code').iterdir() if p.suffix in ['.cpp','.hpp']}))
 except BaseException as exc:
  save('failed');write(a.out/'error.json',dict(error=repr(exc),completed=len(records)));raise
if __name__=='__main__':main()
