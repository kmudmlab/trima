#!/usr/bin/env python3
"""Timing 완료 뒤 application replay. TT 접근·clock 변경·설치 없음."""
import argparse,csv,fcntl,hashlib,json,os,random,re,shutil,socket,struct,subprocess,time
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=Path('/data0/hmpark/gpu_tt_portability_20261021');OLD=Path('/data0/hmpark/tritt-gpu-20260908')
METRICS=['lts__t_sector_hit_rate.pct','lts__t_sectors.sum','lts__t_sectors_lookup_hit.sum','l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum','l1tex__t_requests_pipe_lsu_mem_global_op_ld.sum','sm__warps_active.avg.pct_of_peak_sustained_active','smsp__thread_inst_executed.sum','smsp__inst_executed.sum']
NCU='/usr/local/cuda-12.1/bin/ncu'
def write(p,d):
 tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n');tmp.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--ranking',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
assert socket.gethostname()=='dmlab-bear0';a.out.mkdir(parents=True,exist_ok=False);records=[]
def save(status,active=None):write(a.out/'status.json',dict(status=status,pid=os.getpid(),active=active,records=records))
try:
 while True:
  p=a.ranking/'status.json'
  if p.exists():
   try:s=json.loads(p.read_text())
   except json.JSONDecodeError:time.sleep(2);continue
   assert not s['status'].startswith('failed'),'Timing failed; profile must not start'
   if s['status']=='complete':break
  save('waiting_for_ranking_complete');time.sleep(30)
 save('waiting_for_host_lock');host=(ROOT/'cpu-or-gpu.lock').open('a');fcntl.flock(host,fcntl.LOCK_EX)
 save('waiting_for_gpu_lock');gpu=(ROOT/'gpu.lock').open('a');fcntl.flock(gpu,fcntl.LOCK_EX)
 from gpu_state import wait_idle
 wait_idle(save);build=a.out/'build';build.mkdir()
 for f in (P/'profiling').iterdir():shutil.copy2(f,build/f.name)
 for f in ['trust_kernel.cuh','tricore_kernel.cuh']:shutil.copy2(OLD/'src/baselines'/f,build/f)
 shutil.copy2(OLD/'paper_runs/2026-09-27-review-completion-ede0/wetric/wetric_instrumented.cu',build/'wetric_instrumented.cu')
 binaries={}
 for family in ['trust','tricore','wetric','steptc']:
  binary=(build/(family+'_profile')).resolve();binaries[family]=binary
  sources=[build/'baseline_driver.cu'] if family in ['trust','tricore'] else [build/'wetric_driver.cu'] if family=='wetric' else [build/'steptc_driver.cpp',build/'steptc.cu']
  cccl=OLD/'src/cccl'
  extra=['-I'+str(cccl/d) for d in ['cub','thrust','libcudacxx/include']] if family=='wetric' else []
  cmd=['/usr/local/cuda-12.1/bin/nvcc','-O3','-std=c++17' if family=='wetric' else '-std=c++14','-arch=sm_89','-Xcompiler','-pthread',*extra,*(['-DTRUST'] if family=='trust' else []),*map(str,sources),'-o',str(binary)]
  with (build/(family+'.log')).open('x') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
 write(a.out/'manifest.json',dict(parser_sha256=sha(P/'metrics_report.py'),runner_sha256=sha(Path(__file__)),csv_export_units='base',metrics=METRICS,replay='application',cache_control='none',clock_control='none',profile_from_start='off',cccl_commit=subprocess.check_output(['git','-C',str(OLD/'src/cccl'),'rev-parse','HEAD'],text=True).strip(),binary_sha256={k:sha(v) for k,v in binaries.items()},source_sha256={p.name:sha(p) for p in build.iterdir() if p.suffix in ['.cu','.cpp','.cuh','.h']}))
 def run(name,family,path,count,graph,block=None):
  dst=a.out/name;dst.mkdir();report=dst/'report'
  app=[str(binaries[family])]
  if family=='wetric':app+=['run',str(path),'10','8192','1',str(count)]
  else:app+=[str(path),str(count)]+([] if family=='steptc' else ['1'])
  pattern={'trust':'dynamic_assign','tricore':'warp_binary_kernel','wetric':'tc_GPU_kernel','steptc':'StepTC_.*'}[family]
  cmd=[NCU,'--replay-mode','application','--app-replay-match','grid','--cache-control','none','--clock-control','none','--profile-from-start','off','--kernel-name','regex:'+pattern,'--metrics',','.join(METRICS),'--export',str(report),*app]
  wait_idle(save,dst);start=time.time()
  with (dst/'stdout.log').open('x') as log:
   child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT);save('running',dict(name=name,pid=child.pid,command=cmd));rc=child.wait()
  out=(dst/'stdout.log').read_text();record=dict(name=name,family=family,graph=graph,block=block,returncode=rc,wall_s=time.time()-start,command=cmd);records.append(record)
  assert rc==0 and '==ERROR==' not in out,name
  samples=[];coverage=[]
  for line in out.splitlines():
   if not line.startswith('{'):continue
   try:d=json.loads(line)
   except json.JSONDecodeError:continue
   if d.get('kind')=='sample':samples.append(d)
   if d.get('kind')=='profile_coverage':coverage.append(d['expected_launches'])
  assert samples and all(x['count']==count for x in samples),name+' correctness'
  assert (dst/'report.ncu-rep').exists()
  export_cmd=[NCU,'--import',str(dst/'report.ncu-rep'),'--page','raw','--csv','--print-units','base']
  write(dst/'csv-export-command.json',export_cmd)
  with (dst/'metrics.csv').open('x') as f,(dst/'csv-export-stderr.log').open('x') as err:subprocess.run(export_cmd,stdout=f,stderr=err,check=True)
  assert any(x.get('warmup') is True for x in samples) and any(x.get('warmup') is False for x in samples),name+' sample phases'
  from metrics_report import summarize_cell,replay_metadata
  metric_summary=summarize_cell(dst/'metrics.csv',METRICS)
  write(dst/'derived-metrics.json',metric_summary)
  with open(path,'rb') as f:n,m=struct.unpack('<II',f.read(8))
  expected_launches=1 if family in ['trust','wetric'] else (m+16777215)//16777216 if family=='tricore' else coverage[0] if coverage else None
  assert expected_launches is not None and metric_summary['launch_count']==expected_launches,(name,'Count launch coverage',expected_launches,metric_summary['launch_count'])
  replay=replay_metadata(out)
  record.update(status='pass',**replay,raw_profiler_replayer_passes=[k.get('profiler_replayer_passes') for k in metric_summary['kernels']],correct_samples=len(samples),csv_layout=metric_summary['csv_layout'])
  write(dst/'summary.json',record);save('running');print('PASS',name,record['wall_s'],replay,flush=True)
 for family in binaries:
  path=ROOT/'cpu-validation/clique140.csr';run('pilot-'+family,family,path,447580,'clique140')
  if family=='trust':write(a.out/'pilot-gate.json',dict(status='pass',pilot=records[-1],definition='First corrected pilot passed before other pilots and graph campaign'))
 write(a.out/'pilot-summary.json',records)
 # Planning estimate only: scale measured ranking process wall times by the
 # corresponding fixture profile/timing process ratio. Re-estimate after large graphs.
 factors={r['family']:r['wall_s']/next(x['wall_s'] for x in s['records'] if x['name']=='fixture-clique140-'+r['family']) for r in records}
 eta=sum(r['wall_s']*factors[r['family']] for r in s['records'] if r.get('block') is not None and r.get('status')=='pass')
 write(a.out/'pilot-eta.json',dict(estimated_remaining_wall_s=eta,family_factors=factors,
  limitation='Planning extrapolation from fixture process wall ratio, not measured graph profile time or an upper bound. Input preparation and launch counts differ.'))
 graphs=json.loads((P/'inputs.json').read_text());inputs=json.loads((a.ranking/'input-manifest.json').read_text());exclusions=s['exceptions']
 for group in [graphs[:4],graphs[4:]]:
  for block in range(3):
   cells=[(g,f) for g in group for f in binaries];random.Random(20261022+block).shuffle(cells)
   for g,f in cells:
    if g['graph']+'/'+f in exclusions:continue
    run(f'block{block}-{g["graph"]}-{f}',f,inputs[g['graph']]['path'],g['expected_count'],g['graph'],block)
 from metrics_report import report
 report(a.out,records)
 save('complete')
except BaseException as exc:
 save('failed');write(a.out/'failure.json',dict(error=repr(exc)));raise
