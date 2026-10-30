#!/usr/bin/env python3
"""Decode only COUNTERS=1 results. Wall ticks across processors overlap."""
import argparse,json
from pathlib import Path
import numpy as np
def extract(cell):
    cfg=json.loads((cell/'config.json').read_text());assert cfg['counters']==1
    a=np.load(cell/'result-1.npy');assert not np.any(a[:,22])
    def vector(w):return [int(r[w])+(int(r[w+1])<<32) for r in a]
    def total(w):return sum(vector(w))
    def by_dm(w):
        values=vector(w);return [sum(values[ch::2]) for ch in range(2)]
    dm=by_dm(32);trisc=[total(w) for w in [34,36,38]]
    assert sum(dm+trisc)==total(4)
    bins=[(i,i) for i in range(5)]+[(2**(i-3)+1,2**(i-2)) for i in range(5,35)]+[(None,None)]*2
    source_hist=[total(128+i*2) for i in range(37)];job_hist=[total(224+i*2) for i in range(65)]
    assert sum(source_hist)==total(2) and sum(job_hist)==total(52)
    high=total(56)+sum(total(64+w*16+8) for w in range(3))
    result=dict(cell=cfg['cell'],input_sha256=cfg['source_sha256'],cores=cfg['cores'],l1_bytes=688128,
        count=total(0),engine_counts=vector(0),candidates=total(4),engine_candidates=vector(4),
        processor_candidates=dict(DM0=dm[0],DM1=dm[1],TRISC0=trisc[0],TRISC1=trisc[1],TRISC2=trisc[2]),
        dm_ack_slot_ticks=by_dm(40),dm_ack_source_ticks=by_dm(42),dm_source_prepare_ticks=by_dm(44),
        dm_target_supply_ticks=by_dm(46),dm_cache_to_arena_copy_ticks=by_dm(48),dm_interval_ticks=by_dm(50),
        trisc_job_wait_ticks=[total(64+w*16) for w in range(3)],
        trisc_wait_during_source_prepare_ticks=[total(66+w*16) for w in range(3)],
        trisc_compute_ticks=[total(68+w*16) for w in range(3)],trisc_interval_ticks=[total(70+w*16) for w in range(3)],
        high_degree_candidates=high,high_degree_candidate_fraction=high/total(4) if total(4) else None,
        source_batch_histogram=[dict(minimum=lo,maximum=hi,count=count) for (lo,hi),count in zip(bins,source_hist)],
        batch_job_histogram=[dict(jobs=i,count=c) for i,c in enumerate(job_hist)],
        cache_misses=[total(w) for w in [8,10,12]],range_requests=[total(w) for w in [360,362,364]],
        range_bytes=[total(w) for w in [366,368,370]],read_barriers=total(54),
        caveats=['processor별 tick 합계는 서로 겹치므로 경과시간이 아니다.',
                 'profile polling의 clock 읽기에는 계측 비용이 있다. 성능 비율은 COUNTERS=0에서만 계산한다.',
                 'source 준비 overlap은 worker가 기다리는 동안 어느 한 producer가 PREP_SOURCE인 시간이며 단독 인과 효과가 아니다.',
                 'ACK/job 대기는 이미 준비된 경우의 확인 비용도 포함한다.'])
    return result
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('cell',type=Path);args=ap.parse_args()
    out=args.cell/'profile.json'
    with out.open('x') as f:json.dump(extract(args.cell),f,indent=2,ensure_ascii=False);f.write('\n')
