"""Bank/ring lifetime interleaving model; not a device memory-order proof."""
from pathlib import Path
import itertools,json,random,hashlib
P=Path(__file__).resolve().parent;out=P/'protocol-context-v1';out.mkdir();records=[]
def simulate(order,delay,case,launch):
 rng=random.Random(20261022+case*100+delay*10+launch);acks=[[0]*3 for _ in range(2)];slots=[None,None];bank=[None,None];last=[0,0];nextw=[1]*3;seq=0;completed=0;published={};steps=0
 def worker(w):
  nonlocal completed,steps
  q=nextw[w];entry=slots[(q-1)%2]
  if entry is None or entry['seq']!=q:return False
  # Reads must still refer to the source generation pinned by this slot.
  assert bank[entry['bank']]==entry['source'],('bank overwritten',entry,bank)
  entry['reads'][w]+=1
  need=1+(entry['source']+w+delay)%5
  if entry['reads'][w]>=need:
   assert acks[(q-1)%2][w]<q;acks[(q-1)%2][w]=q;nextw[w]+=1;completed+=1
  steps+=1;return True
 def sweep():
  for w in order:
   if rng.randrange(1+delay)==0:worker(w)
 def retire(q):
  if not q:return
  waits=0
  while not all(a>=q for a in acks[(q-1)%2]):
   sweep();waits+=1;assert waits<10000
 def prepare(source,b):
  retire(last[b]);bank[b]=source
 def publish(source,b):
  nonlocal seq
  q=seq+1
  if q>2:retire(q-2)
  assert bank[b]==source
  slots[(q-1)%2]=dict(seq=q,bank=b,source=source,reads=[0]*3)
  last[b]=q;seq=q;published[q]=source;sweep()
 total_sources=5+case;prepare(0,0)
 for source in range(total_sources):
  b=source%2
  for batch in range(1+(source+case)%7):
   publish(source,b)
   if batch==0 and source+1<total_sources:prepare(source+1,b^1)
 retire(seq)
 assert completed==3*seq and all(x==seq+1 for x in nextw)
 return dict(published=seq,acks=completed,partial_read_steps=steps)
try:
 for order,delay,case in itertools.product(itertools.permutations(range(3)),range(6),range(6)):
  launches=[simulate(order,delay,case,l) for l in range(3)]
  records.append(dict(order=order,delay=delay,case=case,launches=launches,status='pass'))
 assert len(records)==216
 (out/'COMPLETE.json').write_text(json.dumps(dict(status='pass',schedules=216,launches_per_schedule=3,records=records,kernel_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (P/'code').glob('step_*')},scope='interleaving model; actual producer CPU semantics separate; actual device memory-order/epoch stress still required'),indent=2)+'\n')
except BaseException as e:
 (out/'FAILURE.json').write_text(json.dumps(dict(error=repr(e),records=records),indent=2)+'\n');raise
