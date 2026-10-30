#!/usr/bin/env python3
"""bear CPU 전용: 기존 hash 준비 자료와 slot 대조. GPU/TT 호출 없음."""
import argparse,fcntl,hashlib,json,os,socket,subprocess,time
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=Path('/data0/hmpark/gpu_tt_portability_20261021')
def write(p,x):
 t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n');t.replace(p)
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(16<<20),b''):h.update(b)
 return h.hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
assert socket.gethostname()=='dmlab-bear0';a.out.mkdir(parents=True,exist_ok=False);records=[]
def save(status,active=None):write(a.out/'status.json',dict(status=status,pid=os.getpid(),records=records,active=active))
try:
 save('waiting_for_host_lock');lock=(ROOT/'cpu-or-gpu.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
 graphs=json.loads((P/'inputs.json').read_text());verified={}
 for source,binary in [('compare.cpp','compare'),('cpu_graph.cpp','cpu_graph')]:
  cmd=['g++','-O3','-std=c++17','-Wall','-Wextra','-Werror',str(P/source),'-o',str(a.out/binary)]
  with (a.out/(binary+'-build.log')).open('x') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
 prep=a.out/'cpu-graphs-prepared';prep.mkdir()
 for g in graphs:
  digest=sha(g['input_path']);assert digest==g['input_sha256'],g['graph']+' input SHA mismatch';verified[g['graph']]=digest
  if g.get('road'):continue
  cmd=[str(a.out/'cpu_graph'),g['input_path'],str(int(g['graph']=='webcc'))];save('preparing_cpu_graph',dict(graph=g['graph'],command=cmd))
  with (prep/(g['graph']+'.stdout.json')).open('x') as f:subprocess.run(cmd,stdout=f,check=True)
  d=json.loads((prep/(g['graph']+'.stdout.json')).read_text());d.update(graph=g['graph'],input_sha256=digest,seed=20261022,
    definition='Original collect_cpu.cpp: reservoir 200 rows degree>128, 128 uniform absent keys; extra occupied-slot steps')
  write(prep/(g['graph']+'.json'),d);print('CPU_PREP',g['graph'],flush=True)
 write(prep/'counts-ready.json',dict(status='candidate_counts_ready_awaiting_B0_reference',graphs=14,source_sha256=sha(P/'cpu_graph.cpp'),inputs=verified))
 for g in graphs:
  dst=a.out/g['graph'];dst.mkdir();cmd=[str(a.out/'compare'),g['input_path'],'512',str(dst/'rows.jsonl')]
  start=time.time();save('comparing_slots',dict(graph=g['graph'],command=cmd))
  with (dst/'result.json').open('x') as f,(dst/'stderr.log').open('x') as err:subprocess.run(cmd,stdout=f,stderr=err,check=True)
  d=json.loads((dst/'result.json').read_text());assert (d['n'],d['m'])==(g['n'],g['m'])
  records.append(dict(graph=g['graph'],input_sha256=verified[g['graph']],status='pass',command=cmd,cpu_elapsed_s_not_device_timing=time.time()-start))
  write(dst/'manifest.json',records[-1]);print('HASH_PASS',g['graph'],flush=True)
 write(a.out/'manifest.json',dict(inputs=graphs,source_sha256={f.name:sha(f) for f in P.glob('*.cpp')},row_limit=512,query_limit=1024,uniform_misses_per_row=128,seed_rows=[20261022,20261023],probe_definition='slots inspected, including terminal empty/equal slot; prior counter extra steps = this value - 1'))
 save('complete')
except BaseException as e:
 save('failed');write(a.out/'failure.json',dict(error=repr(e)));raise
