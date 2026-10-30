#!/usr/bin/env python3
"""Independent triple-enumeration oracle, including degree and DMA boundaries."""
import argparse, itertools, json, subprocess, tempfile
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
def graph(n,edges):
    rows=[[] for _ in range(n)]
    for a,b in sorted(set(tuple(sorted(e)) for e in edges)):
        if a!=b:rows[a].append(b)
    rp=np.zeros(n+1,dtype=np.uint32)
    rp[1:]=np.cumsum([len(r) for r in rows],dtype=np.uint64)
    col=np.asarray(list(itertools.chain.from_iterable(rows)),dtype=np.uint32)
    return np.concatenate([np.asarray([n,len(col)],dtype=np.uint32),rp,col])
def exact(n,edges):
    adjacent=[set() for _ in range(n)]
    for a,b in edges:
        if a!=b:adjacent[a].add(b);adjacent[b].add(a)
    return sum(1 for a in range(n) for b in adjacent[a] if a<b for c in adjacent[a]&adjacent[b] if b<c)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--opt-level',type=int,default=2);args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    binary=args.out/'prepare';subprocess.run(['c++','-O2','-std=c++17',f'-DOPT_LEVEL={args.opt_level}',str(HERE/'prepare.cpp'),'-o',str(binary)],check=True)
    cases=[('empty',10,[]),('single',3,[(0,1),(0,2),(1,2)]),('clique40',40,list(itertools.combinations(range(40),2))),('clique140',140,list(itertools.combinations(range(140),2)))]
    edges=[(0,i) for i in range(1,2051)]+[(1,i) for i in range(2,2051)]+[(128,2048),(1024,2049)]
    cases.append(('long-collision-boundary',2053,edges))
    rng=np.random.default_rng(20261021)
    for i in range(32):
        n=int(rng.integers(3,100));p=float(rng.uniform(.01,.7));edges=[(u,v) for u in range(n) for v in range(u+1,n) if rng.random()<p]
        cases.append((f'random{i}',n,edges))
    records=[]
    for name,n,edges in cases:
        data=graph(n,edges);path=args.out/(name+'.csr');data.astype('<u4').tofile(path);want=exact(n,edges)
        for mode in (1,2,3,4,5):
            for engines in (1,7,220):
                tail=min(n,65) if engines==7 else 0
                aux=args.out/f'{name}-{mode}-{engines}.aux'
                result=json.loads(subprocess.check_output([str(binary),str(path),str(aux),str(mode),str(tail),str(engines)],text=True))
                assert result['count']==want,(name,mode,engines,result['count'],want)
                records.append(dict(case=name,mode=mode,engines=engines,tail=tail,expected=want,**result));aux.unlink()
        (args.out/(name+'.json')).write_text(json.dumps(dict(n=n,count=want),indent=2)+'\n')
    (args.out/'verification.json').write_text(json.dumps(dict(status='pass',cases=len(cases),checks=len(records),records=records),indent=2)+'\n')
    print(json.dumps(dict(status='pass',cases=len(cases),checks=len(records))))
if __name__=='__main__':main()
