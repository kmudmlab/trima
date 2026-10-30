# Read-only historical count extraction. Does not import ttnn or open a device.
from pathlib import Path
import json,hashlib
import numpy as np
G=Path('/home/dmlab/tritt/experiments/gpu_tt_portability_20261021/optimization_20261022/gap');P=G/'task35-final-v1'
x=json.loads((P/'timing/COMPLETE.json').read_text());out={}
for r in x['records']:
 if r.get('block')!=0 or r.get('group')!='A' or r.get('variant')!='L0' or r['graph']=='webcc':continue
 p=P/r.get('cell','timing/'+r['name']);npfile=p/'result-0.npy';a=np.load(npfile)
 counts=[int(v[0])+(int(v[1])<<32) for v in a]
 assert len(counts)==220
 conf=json.loads((p/'config.json').read_text())
 out[r['graph']]=dict(counts220=counts,input_sha256=conf['input_sha256'],reference=str(npfile),reference_sha256=hashlib.sha256(npfile.read_bytes()).hexdigest())
assert len(out)==16
print(json.dumps(out,indent=2))
