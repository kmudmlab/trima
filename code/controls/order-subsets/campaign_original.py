#!/usr/bin/env python3
"""Approved Task 6: existing TRUST kernel only; all profiles before timing."""
import argparse, datetime, fcntl, hashlib, itertools, json, os, random, subprocess, sys, time, traceback
from pathlib import Path
import numpy as np
G=Path(__file__).resolve().parent.parent
RUN=G/'order-dependence/original_host.py'
SUBSETS=[''.join(c) or 'B0' for k in range(5) for c in itertools.combinations('PHSW',k) if 'W' not in c or {'H','S'}<=set(c)]
def members(s): return set() if s=='B0' else set(s)
ORDERS=[''.join(p) for p in itertools.permutations('PHSW') if p.index('W')>p.index('H') and p.index('W')>p.index('S')]
def now(): return datetime.datetime.now().astimezone().isoformat()
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(16<<20),b''): h.update(b)
 return h.hexdigest()
def write(p,d):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2)+'\n');t.replace(p)
def total(a,col): return sum(int(r[col])+(int(r[col+1])<<32) for r in a)
def idle():
 with (G.parent/'hardware.lock').open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  r=subprocess.run(['fuser','/dev/tenstorrent/0'],capture_output=True,text=True)
  assert r.returncode==1 and not r.stdout.strip(),('device occupied or fuser error',r.stdout,r.stderr)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();O=args.out.resolve();O.mkdir(exist_ok=False,parents=True)
 state=dict(status='preflight',pid=os.getpid(),started_at=now(),planned_cells=80,records=[])
 locks=[]
 try:
  for p in [G/'trima-supply-v1/downstream.lock',G/'hash-mix/priority-queue.lock']:
   f=p.open('a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(f)
  idle()
  graphs={x['graph']:x for x in json.loads((G/'suite-v1/preflight.json').read_text())['graphs'] if x['graph'] in ('comlj','orkut')}
  refs={};checks={}
  for g,x in graphs.items():
   assert sha(x['input_path'])==x['input_sha256']
   base=G/'suite-v1'/f'{g}-source-continue-v1'
   r0=base/'profile-B0/result-1.npy';rP=base/'profile-B2/result-1.npy'
   a,b=np.load(r0),np.load(rP);assert a.shape==b.shape==(220,1024)
   assert np.array_equal(a[:,:2],b[:,:2]);assert total(a,0)==x['expected_count']
   old=G/'bottomup-v1'/f'{g}-profile-B1-prune/samples.jsonl'
   oldrows=[json.loads(l) for l in old.read_text().splitlines()]
   oldcfg=next(r for r in oldrows if r['kind']=='config');assert oldcfg['input_sha256']==x['input_sha256']
   vals={r['metrics']['candidates'] for r in oldrows if r['kind']=='sample'}
   assert vals=={total(b,4)}
   refs[g]=(r0,rP);checks[g]=dict(input_sha256=x['input_sha256'],B0_candidates=total(a,4),B1_candidates=total(b,4),B1_total_reference=str(old),pruned_vector_reference=str(rP),count_reference=str(r0),reference_sha256={str(p):sha(p) for p in (old,r0,rP)})
  write(O/'REFERENCE_CHECKS.json',checks)
  jobs=[(g,s) for g in ('comlj','orkut') for s in SUBSETS]
  schedule=[dict(graph=g,subset=s,phase='profile',block=None) for g,s in jobs]
  for block in range(3):
   shuffled=jobs.copy();random.Random(20261022+block).shuffle(shuffled)
   schedule += [dict(graph=g,subset=s,phase='timing',block=block) for g,s in shuffled]
  assert len(SUBSETS)==10 and len(ORDERS)==8 and len(schedule)==80
  write(O/'PLAN.json',dict(subsets=SUBSETS,orders=ORDERS,excluded=['HW','PHW'],dependency='W requires H and S',schedule=schedule,source_sha256={str(p):sha(p) for p in (Path(__file__),RUN,G/'run_trust_gap.py',G/'trust_gap_kernel.cpp')},estimate_minutes=[10,15],estimate_basis='Previous 36-cell TRUST campaigns: comlj 128.513435 s, orkut 282.650179 s; 40 cells each proxy 7.61 min, allowance for slower unpruned configurations and JIT.'))
  state['status']='running';write(O/'status.json',state)
  for job in schedule:
   g,s,phase,block=job['graph'],job['subset'],job['phase'],job['block'];x=graphs[g];bits=members(s);profile=phase=='profile'
   name=f'{g}-{phase}-'+('' if profile else f'b{block}-')+s
   dest=O/name;countref,candref=refs[g];candref=candref if 'P' in bits else countref
   expected_cand=checks[g]['B1_candidates' if 'P' in bits else 'B0_candidates']
   if not profile: countref=O/f'{g}-profile-{s}'/'result-1.npy'
   cmd=[sys.executable,str(RUN),'--input',x['input_path'],'--out',str(dest),'--expected',str(x['expected_count']),'--engine-counts',x['metadata_path'],'--reference',str(countref),'--reps','1' if profile else '3','--cores','110','--page-bytes','16384' if 'S' in bits else '1024','--row-cache-kib','16','--col-cache-kib','64','--bucket-cap','100','--hash-size','16384','--hash-mix','0','--prune',str(int('P' in bits)),'--hash-oa',str(int('H' in bits)),'--direct',str(int('S' in bits)),'--lookup-width','4' if 'W' in bits else '1','--meta-stage','64','--arena-kib','64','--chunk-kib','1048576']
   if profile: cmd+=['--profile','--expected-candidates',str(expected_cand),'--candidate-reference',str(candref)]
   idle();record=dict(job,name=name,status='running',started_at=now(),command=cmd);state['records'].append(record);state['active_cell']=name;write(O/'status.json',state)
   start=time.monotonic()
   with (O/(name+'.log')).open('w') as log:
    proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT);record['pid']=proc.pid;write(O/'status.json',state);rc=proc.wait()
   record.update(returncode=rc,wall_s=time.monotonic()-start,finished_at=now())
   assert rc==0,(name,rc)
   summary=json.loads((dest/'summary.json').read_text());assert summary['status']=='pass'
   config=json.loads((dest/'config.json').read_text());assert config['input_sha256']==x['input_sha256']
   ref=np.load(countref);cand=np.load(candref)
   for rep in range(2 if profile else 4):
    a=np.load(dest/f'result-{rep}.npy');assert np.array_equal(a[:,:2],ref[:,:2]);assert total(a,0)==x['expected_count']
    if profile: assert total(a,4)==expected_cand and np.array_equal(a[:,4:6],cand[:,4:6])
   record.update(status='pass',median_s=summary['median_s'],l1_bytes=summary['l1_bytes'],count_exact=True,candidate_exact=True if profile else None,candidates=expected_cand if profile else None)
   write(O/'status.json',state)
  state.update(status='complete',finished_at=now(),active_cell=None);write(O/'status.json',state)
 except BaseException as e:
  if state['records'] and state['records'][-1]['status']=='running':state['records'][-1]['status']='failed'
  state.update(status='failed',finished_at=now(),error=repr(e));write(O/'status.json',state);write(O/'failure.json',dict(error=repr(e),traceback=traceback.format_exc()));raise
 finally:
  for f in locks:f.close()
if __name__=='__main__':main()
