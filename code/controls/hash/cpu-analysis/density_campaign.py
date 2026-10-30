"""bear CPU 전용, d+>128 행 전수 밀도 통계. 기존 결과 덮어쓰기 금지."""
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
a=argparse.ArgumentParser();a.add_argument('--out',type=Path,required=True);a=a.parse_args()
assert socket.gethostname()=='dmlab-bear0';a.out.mkdir(parents=True,exist_ok=False);records=[]
def save(status,active=None):write(a.out/'status.json',dict(status=status,pid=os.getpid(),records=records,active=active))
try:
 save('waiting_for_host_lock');lock=(ROOT/'cpu-or-gpu.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
 with (a.out/'build.log').open('x') as log:subprocess.run(['g++','-O3','-std=c++17','-Wall','-Wextra','-Werror',str(P/'density.cpp'),'-lz','-o',str(a.out/'density')],stdout=log,stderr=subprocess.STDOUT,check=True)
 for g in json.loads((P/'inputs.json').read_text()):
  save('running',g['graph']);assert sha(g['input_path'])==g['input_sha256']
  dst=a.out/g['graph'];dst.mkdir();start=time.time()
  with (dst/'result.json').open('x') as f,(dst/'stderr.log').open('x') as err:subprocess.run([str(a.out/'density'),g['input_path'],str(dst/'rows.csv.gz')],stdout=f,stderr=err,check=True)
  d=json.loads((dst/'result.json').read_text());assert (d['n'],d['m'])==(g['n'],g['m'])
  records.append(dict(graph=g['graph'],input_sha256=g['input_sha256'],status='pass',rows=d['all_degree_gt_128']['rows'],cpu_elapsed_s_not_device_timing=time.time()-start))
  print('DENSITY_PASS',g['graph'],records[-1]['rows'],flush=True)
 write(a.out/'manifest.json',dict(records=records,source_sha256=sha(P/'density.cpp'),coverage='all rows with forward degree >128; no row sampling',rank='zero based; rho denominator exactly n-rank'))
 save('complete')
except BaseException as e:
 save('failed');write(a.out/'failure.json',dict(error=repr(e)));raise
