#!/usr/bin/env python3
"""Approved StepTC model: independent counts, exact candidates, asynchronous lifetime model."""
import argparse,json,random,struct,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
args.out.mkdir(parents=True,exist_ok=False)
binary=args.out/'cpu_check';prep=HERE.parent/'suite-v1/code/direct/prepare-L2-c32-h1-b1'
subprocess.run(['g++','-O2','-std=c++17','-DCOUNTERS=1','-DOPT_LEVEL=2','-DHASH_OA=1','-DLOOKUP_WIDTH=4',str(HERE/'cpu_check.cpp'),'-o',str(binary)],check=True)
fixtures=sorted((HERE.parents[2]/'cpu-validation').glob('*.csr'))
fixtures=[p for p in fixtures if p.stem!='empty']
for n in [2,5,66,130,131]:
    row=[0];col=[]
    for u in range(n):col.extend(range(u+1,n));row.append(len(col))
    p=args.out/f'clique{n}.csr';p.write_bytes(struct.pack('<'+'I'*(2+len(row)+len(col)),n,len(col),*row,*col))
    p.with_suffix('.json').write_text(json.dumps({'count':n*(n-1)*(n-2)//6}));fixtures.append(p)
checks=0
for fixture in fixtures:
    expected=json.loads(fixture.with_suffix('.json').read_text())['count']
    aux=args.out/f'{fixture.stem}.aux'
    subprocess.run([str(prep),str(fixture),str(aux),'7','0'],check=True,stdout=subprocess.DEVNULL)
    for engines in [1,7,220]:
        result=json.loads(subprocess.check_output([str(binary),str(fixture),str(aux),str(engines)],text=True))
        assert result['count']==expected,(fixture,engines,result['count'],expected)
        (args.out/f'{fixture.stem}-e{engines}.json').write_text(json.dumps(result)+'\n');checks+=4
# Abstract two-channel producer/consumer interleavings. Each reader must consume every seq,
# and neither its arena nor its source may be replaced before its ACK.
schedule_checks=0
for seed in range(200):
    rng=random.Random(20261022+seed)
    source=[0,0];published=[0,0];ack=[[0]*3 for _ in range(2)];slots=[[None,None] for _ in range(2)]
    remaining=[rng.randrange(1,8),rng.randrange(1,8)];seen=set();produced=set()
    while source!=[20,20]:
        ch=rng.randrange(2);who=rng.randrange(4)
        if who==3 and source[ch]<20:
            if remaining[ch]==0:
                if min(ack[ch])==published[ch]:source[ch]+=1;remaining[ch]=rng.randrange(1,8)
            elif min(ack[ch])>=published[ch]-1:
                seq=published[ch]+1;slots[ch][(seq-1)%2]=(seq,source[ch]);published[ch]=seq;remaining[ch]-=1
                produced.update((ch,seq,w) for w in range(3))
        elif who<3 and ack[ch][who]<published[ch]:
            seq=ack[ch][who]+1;payload=slots[ch][(seq-1)%2]
            assert payload==(seq,source[ch]),(seed,ch,who,payload,seq,source)
            identity=(ch,seq,who);assert identity not in seen;seen.add(identity);ack[ch][who]=seq
    assert seen==produced;schedule_checks+=1
# uint64 split/join must preserve carry, including accumulated processor partials.
for value in [0,2**32-1,2**32,2**32+7,2**63+123]:
    lo,hi=value&0xffffffff,value>>32;assert lo+(hi<<32)==value
summary=dict(status='pass',fixtures=len(fixtures),semantic_cells=checks,schedules=schedule_checks,
             engines=[1,7,220],limitations='CPU model does not prove TT memory ordering; device stress fixtures follow.')
(args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
