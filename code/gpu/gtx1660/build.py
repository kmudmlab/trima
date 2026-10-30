from pathlib import Path
import json,hashlib,subprocess,shutil,os,socket,traceback
P=Path(__file__).resolve().parent;OLD=Path('/data0/hmpark/tritt-gpu-20260908');R=Path('/data0/hmpark/gpu_tt_portability_20261021');NV='/usr/local/cuda-12.1/bin/nvcc'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def wr(p,d):p.write_text(json.dumps(d,indent=2)+'\n')
assert socket.gethostname()=='dmlab-bear0' and os.getpriority(os.PRIO_PROCESS,0)>=10
B=P/'binaries';B.mkdir(exist_ok=False);S=P/'sources';S.mkdir()
cc=OLD/'src/cccl';w=OLD/'paper_runs/2026-09-27-review-completion-ede0/wetric';step=R/'gpu-ranking-code/steptc'
commands={
 'trust':[NV,'-O3','-arch=sm_89','-DTRUST','-I'+str(OLD/'src/baselines'),str(OLD/'gpu_baselines_driver.cu')],
 'tricore':[NV,'-O3','-arch=sm_89','-I'+str(OLD/'src/baselines'),str(OLD/'gpu_baselines_driver.cu')],
 'wetric':[NV,'-O3','-std=c++17','-arch=sm_89',*['-I'+str(cc/d) for d in ['cub','thrust','libcudacxx/include']],str(w/'driver.cu')],
 'steptc':[NV,'-O3','-std=c++14','-arch=sm_89','-Xcompiler','-pthread',str(step/'driver.cpp'),str(step/'tricount.cu')]
}
files=[OLD/'gpu_baselines_driver.cu',OLD/'src/baselines/trust_kernel.cuh',OLD/'src/baselines/tricore_kernel.cuh',w/'driver.cu',w/'wetric_instrumented.cu',step/'driver.cpp',step/'tricount.cu',step/'tricount.h']
manifest={}
for i,f in enumerate(files):
 d=S/f'{i}-{f.name}';shutil.copy2(f,d);manifest[str(f)]=dict(sha256=sha(f),snapshot=str(d.relative_to(P)))
assert sha(files[0])=='ef3055c1d1b9d71d3e8777b9bf43ddfaec7506fdb95cb6620afb1ebb20a68f16'
wr(P/'source-manifest.json',dict(files=manifest,cccl_commit=subprocess.check_output(['git','-C',str(cc),'rev-parse','HEAD'],text=True).strip(),cccl_dirty=subprocess.check_output(['git','-C',str(cc),'status','--porcelain'],text=True),source_changes=False))
(P/'nvcc-version.txt').write_text(subprocess.check_output([NV,'--version'],text=True))
wr(P/'original-sm89-commands.json',commands)
prior=json.loads((R/'gpu-ranking-v3/binary-manifest.json').read_text());build={}
try:
 for fam,base in commands.items():
  assert sha(prior[fam]['path'])==prior[fam]['sha256']
  cmd=[x.replace('-arch=sm_89','-arch=sm_75') for x in base]+['--cudart=static','-o',str(B/(fam+'_bench'))]
  wr(P/(fam+'-build-command.json'),dict(command=cmd,original_flags=base,changes=['sm_89 -> sm_75','explicit --cudart=static (nvcc default already static)','output path'],source_changes=False))
  with (P/(fam+'-build.log')).open('x') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
  binary=B/(fam+'_bench');ldd=subprocess.check_output(['ldd',str(binary)],text=True);(P/(fam+'-ldd.txt')).write_text(ldd);assert 'libcudart.so' not in ldd
  build[fam]=dict(path=str(binary),relative_path=str(binary.relative_to(P)),sha256=sha(binary),prior_sm89=prior[fam],command=cmd)
  wr(P/'binary-manifest.json',build);print('BUILT',fam,flush=True)
 wr(P/'BUILD_COMPLETE.json',dict(status='complete',binaries=build,source_manifest_sha256=sha(P/'source-manifest.json')))
except BaseException as e:
 wr(P/'BUILD_FAILURE.json',dict(error=repr(e),traceback=traceback.format_exc()));raise
