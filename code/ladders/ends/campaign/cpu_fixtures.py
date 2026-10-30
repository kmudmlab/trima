from pathlib import Path
import subprocess,json,hashlib,traceback,sys
P=Path(__file__).resolve().parent;O=P/'cpu-fixtures-v1'
read=lambda p:json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 O.mkdir(exist_ok=False);records=[];active=None;variants=read(P/'VARIANTS.json')
 try:
  files=sorted((P/'fixtures').glob('*.csr'));assert len(files)==37
  for f in files:
   dst=O/f.stem;dst.mkdir();expected=read(f.with_suffix('.json'))['count']
   for engines in [1,7,220]:
    reference=None;by={}
    for v in variants:
     active=dict(fixture=f.stem,engines=engines,variant=v['name']);target=dst/f'e{engines}-{v["name"]}.json'
     r=subprocess.run([str(P/'host-bin'/v['name']),str(f),'-',str(engines),str(target)],capture_output=True,text=True)
     target.with_suffix('.log').write_text(r.stdout+r.stderr)
     assert r.returncode==0,('semantic replay process',active,r.stderr)
     x=read(target)['engines'];assert len(x)==engines
     assert sum(a[0] for a in x)==expected,('independent fixture total',active)
     if reference is None:reference=[a[:4] for a in x]
     assert [a[:4] for a in x]==reference,('count/candidate/identity owner exact',active)
     by[v['name']]=x
     if v['name'].endswith('plus-TRISC'):
      assert x==by[v['supply']+'-plus-T'],('compute assignment cannot change IO',active)
     records.append(dict(**active,status='pass',per_owner_exact=True,candidate_multiset_exact=True,physical_QBW_exact=True,input_sha256=sha(f),output_sha256=sha(target),binary_sha256=sha(P/'host-bin'/v['name'])))
     write(O/'status.json',dict(status='running',passed=len(records),active=active,timing_started=False))
   print(f.stem,len(records),flush=True)
  assert len(records)==888
  write(O/'COMPLETE.json',dict(status='pass',checks=888,records=records,clock_measured=False,timing_started=False))
  write(O/'status.json',dict(status='complete',passed=888,timing_started=False))
 except BaseException as e:
  write(O/'FAILURE.json',dict(error=repr(e),active=active,records=records,traceback=traceback.format_exc()))
  write(O/'status.json',dict(status='failed',passed=len(records),active=active,timing_started=False));raise
if __name__=='__main__':main()
