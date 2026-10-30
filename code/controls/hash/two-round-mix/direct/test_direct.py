#!/usr/bin/env python3
"""CPU check of gap/direct: each direct variant must reproduce, per engine, the counts of the
baseline function with the same ownership (StepTC opt2, WeTriC opt2, TriCore-COO opt3), and the
TC grid must match COO opt3 at (32,1,1) and the independent count everywhere."""
import itertools,json,subprocess,sys,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;FIX=HERE.parents[4]/'cpu-validation'
def build(name,**d):
    out=Path(tempfile.gettempdir())/f'direct-{name}';flags=[f'-D{k}={v}' for k,v in d.items()]
    subprocess.run(['g++','-O2','-std=c++17','-Wall','-Wno-unused-variable','-Wno-unused-but-set-variable',*flags,str(HERE/'prepare.cpp'),'-o',str(out)],check=True);return out
def run(binary,fx,mode,engines):
    with tempfile.TemporaryDirectory() as t:
        return json.loads(subprocess.check_output([str(binary),str(FIX/f'{fx}.csr'),str(Path(t)/'aux.bin'),str(mode),'0',str(engines)],text=True))
bins={'L2':build('L2',OPT_LEVEL=2),'L3':build('L3',OPT_LEVEL=3)}
variants={'oa0-bl0-w1':dict(HASH_OA=0,BRANCHLESS=0,LOOKUP_WIDTH=1),'oa1-bl0-w1':dict(HASH_OA=1,BRANCHLESS=0,LOOKUP_WIDTH=1),
          'oa1-bl0-w4':dict(HASH_OA=1,BRANCHLESS=0,LOOKUP_WIDTH=4),'oa1-bl1-w1':dict(HASH_OA=1,BRANCHLESS=1,LOOKUP_WIDTH=1),
          'oa1-bl1-w4':dict(HASH_OA=1,BRANCHLESS=1,LOOKUP_WIDTH=4),'oa0-bl1-w4':dict(HASH_OA=0,BRANCHLESS=1,LOOKUP_WIDTH=4)}
for k,d in variants.items():bins[k]=build(k,OPT_LEVEL=2,**d)
grid={f'g{c}{h}{b}':build(f'g{c}{h}{b}',OPT_LEVEL=2,TC_CHUNK=c,TC_HELD=h,TC_BOUND=b) for c,h,b in itertools.product([1,32],[0,1],[0,1])}
fixtures=sorted(p.stem for p in FIX.glob('*.csr') if p.stem!='empty');checks=0
for fx in fixtures:
    want=json.loads((FIX/f'{fx}.json').read_text())['count']
    for engines in [1,7,220]:
        base={3:run(bins['L2'],fx,3,engines),2:run(bins['L2'],fx,2,engines),6:run(bins['L3'],fx,6,engines)}
        for b in base.values():assert b['count']==want,(fx,b['count'],want)
        for k in variants:
            for mode,ref in [(7,3),(8,2),(9,6)]:
                r=run(bins[k],fx,mode,engines);assert r['engine_counts']==base[ref]['engine_counts'],(fx,engines,k,mode);checks+=1
        for k,bn in grid.items():
            r=run(bn,fx,10,engines);assert r['count']==want,(fx,engines,k)
            if k=='g3211':assert r['engine_counts']==base[6]['engine_counts'],(fx,engines,k)
            checks+=1
print(json.dumps(dict(status='pass',fixtures=len(fixtures),checks=checks)))
