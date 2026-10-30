#!/usr/bin/env python3
"""bear only, no counters. Independent cells, 3 seeded blocks, 1 warmup + 3 Count samples."""
import argparse,csv,fcntl,hashlib,json,os,random,socket,statistics,subprocess,time
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=Path('/data0/hmpark/gpu_tt_portability_20261021');OLD=Path('/data0/hmpark/tritt-gpu-20260908')
FAMILIES=['trust','tricore','wetric','steptc']
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(16<<20),b''):h.update(block)
 return h.hexdigest()
def write(p,d):
 tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n');tmp.replace(p)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--allow-gdm-display',action='store_true');a=ap.parse_args()
 assert socket.gethostname()=='dmlab-bear0'
 a.out.mkdir(parents=True,exist_ok=False);records=[];verified={};exceptions={}
 def save(status,active=None):write(a.out/'status.json',dict(status=status,pid=os.getpid(),active=active,records=records,exceptions=exceptions,updated_unix=time.time()))
 save('waiting_for_host_lock')
 hostlock=(ROOT/'cpu-or-gpu.lock').open('a');fcntl.flock(hostlock,fcntl.LOCK_EX)
 gpulock=(ROOT/'gpu.lock').open('a');fcntl.flock(gpulock,fcntl.LOCK_EX)
 from gpu_state import wait_idle
 try:
  (a.out/'environment.txt').write_text(subprocess.check_output(['nvidia-smi'],text=True))
  graphs=json.loads((P/'inputs.json').read_text());bdir=a.out/'binaries';bdir.mkdir()
  import shutil
  binaries={}
  for family,path in [('trust',OLD/'src/baselines/trust_bench'),('tricore',OLD/'src/baselines/tricore_bench'),('wetric',OLD/'paper_runs/2026-09-27-review-completion-ede0/wetric/wetric_bench')]:
   dst=bdir/(family+'_bench');shutil.copy2(path,dst);binaries[family]=dst.resolve()
  binary=(bdir/'steptc_bench').resolve()
  cmd=['/usr/local/cuda-12.1/bin/nvcc','-O3','-std=c++14','-arch=sm_89','-Xcompiler','-pthread',str(P/'steptc/driver.cpp'),str(P/'steptc/tricount.cu'),'-o',str(binary)]
  with (a.out/'build.log').open('x') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
  binaries['steptc']=binary
  write(a.out/'binary-manifest.json',{k:dict(path=str(v),sha256=sha(v)) for k,v in binaries.items()})
  total_mem=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.total','--format=csv,noheader,nounits'],text=True).strip())*1024**2
  for g in graphs:
   path=Path(g['input_path'])
   if g['graph']=='friendster' and not path.exists():
    prepared=ROOT/'gpu-ranking-v2/friendster.csr'
    path=prepared if prepared.exists() else a.out/'friendster.csr';compact=(bdir/'compact').resolve()
    subprocess.run(['g++','-O2','-std=c++17',str(P/'compact_isolates.cpp'),'-o',str(compact)],check=True)
    if not path.exists():
     d=subprocess.check_output([str(compact),str(OLD/'data/friendster.wetric.csr'),str(path)],text=True);(a.out/'friendster-compaction.json').write_text(d)
   digest=sha(path);assert digest==g['input_sha256'],g['graph']+' input hash mismatch'
   verified[g['graph']]=dict(path=str(path.resolve()),sha256=digest)
   n,m=g['n'],g['m']
   # Necessary lower bounds only. OOM during a launch is separately preserved.
   required={'trust':24*(n+1)+4*m+1024*1024*100*4+20,'tricore':8*(n+1)+4*m+16777216*8+2048,'wetric':12*(n+1)+4*m+8192*8191//16+8,'steptc':12*m+12*(n+1)}
   for family,size in required.items():
    if size>total_mem:exceptions[g['graph']+'/'+family]=dict(status='not_applicable_capacity',necessary_device_bytes=size,total_device_bytes=total_mem)
   write(a.out/'input-manifest.json',verified)
  def command(family,path,count):
   base=[str(binaries[family])]
   if family=='wetric':return base+['run',str(path),'10','8192','3',str(count)]
   return base+[str(path),str(count)]+([] if family=='steptc' else ['3'])
  def run(name,family,path,expected,graph,block=None):
   dst=a.out/name;dst.mkdir();cmd=command(family,path,expected)
   wait_idle(save,dst);start=time.time()
   with (dst/'stdout.log').open('x') as log:
    child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT);save('running',dict(name=name,pid=child.pid,command=cmd,started_unix=start));rc=child.wait()
   r=dict(name=name,family=family,graph=graph,block=block,command=cmd,returncode=rc,wall_s=time.time()-start);records.append(r)
   output=(dst/'stdout.log').read_text();samples=[]
   for line in output.splitlines():
    try:d=json.loads(line)
    except json.JSONDecodeError:continue
    if d.get('kind')=='sample':samples.append(d)
   if block is not None and rc and ('out of memory' in output.lower() or 'memory allocation' in output.lower()):
    r['status']='not_applicable_capacity';write(dst/'summary.json',r);exceptions[graph+'/'+family]=r;save('running');return
   assert rc==0,(name,rc)
   assert len(samples)==4 and samples[0]['warmup'] and not any(d['warmup'] for d in samples[1:]),name
   assert all(d['count']==expected for d in samples),name+' count mismatch'
   values=[d['resident_s'] for d in samples[1:]];assert all(t>0 for t in values)
   r.update(status='pass',samples=samples,median_s=statistics.median(values),timing='resident_s: Count wall time, launch/sync/reduction/readback; uploads excluded')
   write(dst/'summary.json',r);save('running');print('PASS',name,r['median_s'],flush=True)
  # Fresh independent CPU fixture oracle, before any GPU fixture.
  oracle=(bdir/'count-oracle').resolve();subprocess.run(['g++','-O2','-std=c++17',str(P/'count_oracle.cpp'),'-o',str(oracle)],check=True)
  fixtures=[]
  for fx in ['single','clique40','clique140','long-collision-boundary','random12']:
   path=ROOT/'cpu-validation'/f'{fx}.csr';meta=json.loads((P/'fixtures'/f'{fx}.json').read_text())
   d=json.loads(subprocess.check_output([str(oracle),str(path)],text=True));assert d['merge_count']==d['wedge_count']==meta['count']
   fixtures.append(dict(fixture=fx,input_sha256=sha(path),**d))
  write(a.out/'cpu-fixtures.json',fixtures)
  for f in fixtures:
   for family in FAMILIES:run('fixture-'+f['fixture']+'-'+family,family,ROOT/'cpu-validation'/(f['fixture']+'.csr'),f['merge_count'],f['fixture'])
  for group in [graphs[:4],graphs[4:]]:
   # Finish all large-graph blocks before proceeding to the remaining graphs.
   for block in range(3):
    cells=[(g,f) for g in group for f in FAMILIES];random.Random(20261022+block).shuffle(cells)
    for g,family in cells:
     if g['graph']+'/'+family in exceptions:continue
     run(f'block{block}-{g["graph"]}-{family}',family,verified[g['graph']]['path'],g['expected_count'],g['graph'],block)
  rows=[]
  for g in graphs:
   med={}
   for family in FAMILIES:
    values=[r['median_s'] for r in records if r['graph']==g['graph'] and r['family']==family and r.get('block') is not None and r['status']=='pass']
    if g['graph']+'/'+family in exceptions:rows.append(dict(graph=g['graph'],family=family,status='not_applicable_capacity',median_s=None,rank=None));continue
    assert len(values)==3,(g['graph'],family,len(values));med[family]=statistics.median(values)
   for family,value in med.items():rows.append(dict(graph=g['graph'],family=family,status='measured',median_s=value,rank=1+sum(t<value for t in med.values())))
  write(a.out/'ranking.json',rows)
  with (a.out/'ranking.csv').open('x',newline='') as f:
   w=csv.DictWriter(f,fieldnames=['graph','family','status','median_s','rank']);w.writeheader();w.writerows(rows)
  from ranking_report import report
  report(a.out,rows,records,exceptions,P/'tt-ranking-snapshot.json')
  save('complete')
 except BaseException as exc:
  save('failed');write(a.out/'failure.json',dict(error=repr(exc)));raise
if __name__=='__main__':main()
