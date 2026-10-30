"""Mac CPU 검증: 알려진 비용계수 복원, Task14 완료 gate의 fail-closed 동작."""
import copy,json,tempfile
from pathlib import Path
import numpy as np
import after_task14 as tail
from analyze import fit

rows=[]
for n in [0,1024,4096]:
 for s in [64,128,256,512,1024,2048,4096,8192,16384]:
  for b in [1,2,4,8,16,32]:
   q=220*n;v=q*s;w=q//b
   rows.append(dict(requests=q,bytes=v,barriers=w,ticks=17+3*q+.02*v+11*w))
f=fit(rows,'ticks')
assert f['rank']==4 and f['r2']>.999999
assert np.allclose([f[k] for k in ['delta','alpha','beta','gamma']],[17,3,.02,11],rtol=1e-6,atol=1e-5)
negative=[dict(r,ticks=17-3*r['requests']+.02*r['bytes']+11*r['barriers']) for r in rows]
assert fit(negative,'ticks')['crossover_bytes'] is None
with tempfile.TemporaryDirectory() as d:
 tail.G=Path(d);tail.T=tail.G/'locality-v1/device-v1';tail.T.mkdir(parents=True)
 assert tail.completed()[0] is False
 selection={'rows':[dict(graph=g,family=f,Q_base_cpu=100,Q_D1_cpu=200) for g in ['roadNet-PA','roadNet-TX','roadNet-CA'] for f in ['steptc','wetric','tricore']]}
 sp=tail.G/'locality-v1/selection.json';sp.write_text(json.dumps(selection))
 state=dict(status='complete',pid=2147483647,start_ticks=1,records=[dict(status='pass',returncode=0,phase=phase) for phase,count in [('profile',18),('timing',54)] for _ in range(count)])
 compare=dict(status='complete',selection_sha256=tail.digest(sp),prediction_sha256='d8e4c4f02ab041cb9b7024d2fe10059654dbf72169f35299c8af4138a7bed512',rows=[dict(r,Q_base_device=100,Q_D1_device=200,delta_base=0,delta_D1=0) for r in selection['rows']])
 def save(s,c):
  (tail.T/'status.json').write_text(json.dumps(s));(tail.T/'cpu-device-request-comparison.json').write_text(json.dumps(c))
 save(state,compare);assert tail.completed()[0]
 bad=[]
 c=copy.deepcopy(compare);c['rows'][0]=copy.deepcopy(c['rows'][1]);bad.append((state,c))
 c=copy.deepcopy(compare);c['rows'][0]['Q_base_cpu']=99;bad.append((state,c))
 c=copy.deepcopy(compare);c['rows'][0].update(Q_base_device=101,delta_base=1);bad.append((state,c))
 s=copy.deepcopy(state);s['records'][0]['returncode']=1;bad.append((s,compare))
 for s,c in bad:
  save(s,c)
  try:tail.completed()
  except AssertionError:pass
  else:raise AssertionError('invalid Task14 completion accepted')
 save(state,compare)
 state['status']='running';save(state,compare);assert tail.completed()[0] is False
print('PASS: coefficient recovery; negative-coefficient guard; missing/running/valid Task14; four invalid completion cases')
