#!/usr/bin/env python3
"""Index completed Task 5 observations and exact protocol counts; no cost model."""
import argparse,json,statistics,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
subprocess.run([sys.executable,str(HERE/'analyze_completed.py'),'--out',str(args.out)],check=True)
index=[];phases={};source_hashes={}
for file in sorted(HERE.glob('*/comparison.json')):
    comparison=json.loads(file.read_text());status=json.loads((file.parent/'status.json').read_text())
    assert status['status'] in ['complete','stop_supply_counterexample']
    kind='direct' if 'steptc/base' in comparison['seconds'] else 'source'
    graph=comparison['graph'];records=status['records']
    counts={}
    for r in records:
        assert r['returncode']==0
        phase=r['phase'];counts[phase]=counts.get(phase,0)+1;phases[phase]=phases.get(phase,0)+1
        cell=file.parent/r['name'];cfg=json.loads((cell/'config.json').read_text())
        digest=cfg.get('source_sha256',cfg.get('input_sha256'))
        if graph in source_hashes:assert source_hashes[graph]==digest
        source_hashes[graph]=digest
        if phase=='timing':
            assert cfg['reps']==3 and not cfg.get('profile',cfg.get('counters',False))
            summary=json.loads((cell/'summary.json').read_text());assert len(summary['samples_s'])==3
            assert summary['median_s']==statistics.median(summary['samples_s'])
            assert '--reference' in r['command']
        else:
            assert cfg.get('profile',cfg.get('counters',False)) and cfg['reps']==1
    assert counts['timing']==(27 if kind=='direct' else 18)
    assert counts['profile']==(9 if kind=='direct' else 6)
    if kind=='source':assert counts['original-profile']==3
    index.append(dict(graph=graph,kind=kind,cell_counts=counts,path=str(file.parent),status=status['status']))
fixture=[]
for p in HERE.glob('*/status.json'):
    if 'fixture' not in p.parent.name:continue
    d=json.loads(p.read_text());rs=d.get('records',[])
    if not rs:continue
    fixture.append(dict(path=str(p.parent),status=d['status'],passed=sum(r.get('returncode')==0 for r in rs),failed=sum(r.get('returncode',0)!=0 for r in rs)))
complete=[g for g in source_hashes if {r['kind'] for r in index if r['graph']==g}=={'direct','source'}]
record=dict(complete_graphs=sorted(complete),graph_families=index,real_graph_cell_counts=phases,fixture_campaigns=fixture,input_sha256=source_hashes,
    note_ko='장치 fixture의 초기 단독 smoke 셀은 status.json 없는 경우 이 index에 포함되지 않는다. 문서의 수동 합계와 구분한다. 성능 반례는 검증 실패가 아니다.')
(args.out/'completion-index.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(dict(complete_graphs=len(complete),real_graph_cell_counts=phases)))
