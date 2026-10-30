"""Task39: existing WeTriC binary, only adjacency/tail differs; bear only."""
from pathlib import Path
import json,hashlib,fcntl,subprocess,sys,os,socket,time,datetime,random,statistics,traceback
from gpu_state import wait_idle,snapshot
P=Path(__file__).resolve().parent;ROOT=Path('/data0/hmpark/gpu_tt_portability_20261021');O=P/'timing-v1'
rd=lambda p:json.loads(p.read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(16<<20),b''):h.update(b)
 return h.hexdigest()
def wr(p,d):
 t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n');t.replace(p)
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def main():
 assert socket.gethostname()=='dmlab-bear0';O.mkdir(exist_ok=False);records=[];active=None
 def state(status,a=None):wr(O/'status.json',dict(status=status,pid=os.getpid(),active=active if a is None else a,fixture_passed=sum(r['phase']=='fixture' for r in records),timing_passed=sum(r['phase']=='timing' for r in records),planned_timing=72,records=records,updated_utc=now()))
 state('waiting_for_locks')
 with (ROOT/'cpu-or-gpu.lock').open('a') as hostlock,(ROOT/'gpu.lock').open('a') as gpulock:
  fcntl.flock(hostlock,fcntl.LOCK_EX);fcntl.flock(gpulock,fcntl.LOCK_EX)
  try:
   authorization=rd(P/'AUTHORIZATION.json');assert sha(P/'PREREGISTRATION-25.md')==authorization['preregistration_sha256'];assert authorization['commit'].startswith('4fab6f96')
   binary=rd(P/'binary-manifest.json')['wetric'];exe=Path(binary['path']);assert sha(exe)==binary['sha256']
   graphs=rd(P/'inputs.json');assert len(graphs)==12
   verified=[]
   for g in graphs:
    assert sha(g['input_path'])==g['input_sha256'];verified.append(dict(graph=g['graph'],path=g['input_path'],sha256=g['input_sha256'],expected_count=g['expected_count']))
   fixtures=rd(P/'cpu-fixtures.json')
   for f in fixtures:
    assert f['merge_count']==f['wedge_count'];assert sha(ROOT/'cpu-validation'/(f['fixture']+'.csr'))==f['input_sha256']
   wr(O/'INPUT_VERIFIED.json',dict(graphs=verified,cpu_fixture_reference='gpu-ranking-v3 independent merge_count and wedge_count, reused SHA-verified',fixtures=fixtures,binary=binary))
   (O/'environment.txt').write_text(subprocess.check_output(['nvidia-smi'],text=True))
   order=[]
   for block in range(3):
    cells=[dict(graph=g['graph'],tail=tail) for g in graphs for tail in [8192,0]];random.Random(20261022+block).shuffle(cells);order.append(dict(block=block,seed=20261022+block,cells=cells))
   wr(O/'ORDER.json',order)
   def run(phase,graph,inp,expected,tail,block=None,index=None):
    nonlocal active
    name=(f'fixture-{graph}-tail{tail}' if phase=='fixture' else f'block{block}-{graph}-tail{tail}');dst=O/name;dst.mkdir(exist_ok=False)
    cmd=[str(exe),'run',str(inp),'10',str(tail),'3',str(expected)];assert sha(exe)==binary['sha256']
    active=dict(name=name,phase=phase,graph=graph,tail=tail,block=block,index=index,command=cmd);state('waiting_for_GPU')
    wait_idle(state,dst)
    wr(dst/'COMMAND.json',dict(command=cmd,binary_sha256=binary['sha256'],protocol='fresh process, warmup1+3, resident_s',phase=phase,block=block,index=index))
    active['started_utc']=now()
    with (dst/'stdout.log').open('x') as log:
     child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT);active['pid']=child.pid;state('running');rc=child.wait()
    text,xml,after=snapshot();(dst/'nvidia-smi-after.txt').write_text(text);(dst/'nvidia-smi-after.xml').write_text(xml);wr(dst/'gpu-state-after.json',after)
    assert not after['busy'],('other GPU process detected after cell',after['busy'])
    output=(dst/'stdout.log').read_text();samples=[]
    for line in output.splitlines():
     try:r=json.loads(line)
     except json.JSONDecodeError:continue
     if r.get('kind')=='sample':samples.append(r)
    assert rc==0,(name,rc)
    assert len(samples)==4 and samples[0]['warmup'] and not any(r['warmup'] for r in samples[1:])
    assert all(r['count']==expected and r['spread']==10 and r['adjacency']==tail for r in samples),('count/config mismatch',name)
    values=[r['resident_s'] for r in samples[1:]];assert all(x>0 for x in values)
    result=dict(status='pass',phase=phase,graph=graph,tail=tail,block=block,index=index,command=cmd,returncode=rc,samples=samples,median_s=statistics.median(values),expected_count=expected,count_exact=True,binary_sha256=binary['sha256'],timing='resident_s: Count wall time; kernel launch, sync, reduction/readback included; input upload/preprocessing excluded',started_utc=active['started_utc'],finished_utc=now())
    wr(dst/'summary.json',result);records.append(dict(phase=phase,graph=graph,tail=tail,block=block,index=index,status='pass',median_s=result['median_s'],summary=str((dst/'summary.json').relative_to(P)),summary_sha256=sha(dst/'summary.json'),stdout_sha256=sha(dst/'stdout.log'),finished_utc=result['finished_utc']));active=None;state('running');print('PASS',name,flush=True)
   for f in fixtures:
    for tail in [8192,0]:run('fixture',f['fixture'],ROOT/'cpu-validation'/(f['fixture']+'.csr'),f['merge_count'],tail)
   wr(O/'FIXTURES_COMPLETE.json',dict(status='pass',cells=10,records=records.copy()))
   for b in order:
    for i,c in enumerate(b['cells']):
     g=next(g for g in graphs if g['graph']==c['graph']);run('timing',g['graph'],g['input_path'],g['expected_count'],c['tail'],b['block'],i)
    wr(O/f"BLOCK{b['block']}_COMPLETE.json",dict(status='pass',cells=24,block=b['block'],finished_utc=now()))
   assert len(records)==82
   wr(O/'COMPLETE.json',dict(status='pass',fixture_cells=10,timing_cells=72,records=records,finished_utc=now()));state('complete')
  except BaseException as e:
   wr(O/'failure.json',dict(error=repr(e),active=active,records=records,traceback=traceback.format_exc()));state('failed');raise
if __name__=='__main__':main()
