#!/usr/bin/env python3
"""Only aggregate a fully verified 80-cell campaign."""
import argparse,csv,itertools,json,statistics
from pathlib import Path
from campaign import SUBSETS,ORDERS,members

def csvwrite(p,rows):
 with p.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def analyze(O,doc):
 d=json.loads((O/'status.json').read_text());r=d['records'];assert d['status']=='complete' and len(r)==80 and all(x['status']=='pass' for x in r)
 profiles=[x for x in r if x['phase']=='profile'];timings=[x for x in r if x['phase']=='timing'];assert len(profiles)==20 and len(timings)==60
 rows=[];times={};cb={}
 for g in ('comlj','orkut'):
  for s in SUBSETS:
   cells=sorted([x for x in timings if x['graph']==g and x['subset']==s],key=lambda x:x['block']);assert [x['block'] for x in cells]==[0,1,2]
   assert len({x['l1_bytes'] for x in cells})==1
   med=statistics.median(x['median_s'] for x in cells);times[g,s]=med;cb[g,s]=cells[0]['l1_bytes']
   rows.append(dict(graph=g,subset=s,median_s=med,block0_s=cells[0]['median_s'],block1_s=cells[1]['median_s'],block2_s=cells[2]['median_s'],cb_bytes=cb[g,s],cb_KiB_per_core=cb[g,s]/1024,page_bytes=16384 if 'S' in s else 1024))
 lookup={frozenset(members(s)):s for s in SUBSETS};pairs=[]
 for g in ('comlj','orkut'):
  for s in SUBSETS:
   for x in 'PHSW':
    target=frozenset(members(s)|{x})
    if x not in members(s) and target in lookup:
     t=lookup[target];pairs.append(dict(graph=g,switch=x,before=s,after=t,before_s=times[g,s],after_s=times[g,t],speedup=times[g,s]/times[g,t],before_cb_bytes=cb[g,s],after_cb_bytes=cb[g,t],same_cb=cb[g,s]==cb[g,t]))
 summary=[]
 for g in ('comlj','orkut'):
  for x in 'PHSW':
   pr=[p for p in pairs if p['graph']==g and p['switch']==x];lo=min(pr,key=lambda p:p['speedup']);hi=max(pr,key=lambda p:p['speedup']);vs=[p['speedup'] for p in pr]
   summary.append(dict(graph=g,switch=x,pairs=len(vs),min_speedup=min(vs),median_speedup=statistics.median(vs),max_speedup=max(vs),range_speedup=max(vs)-min(vs),min_pair=lo['before']+'->'+lo['after'],max_pair=hi['before']+'->'+hi['after']))
 orders=[]
 for g in ('comlj','orkut'):
  for order in ORDERS:
   active=set();before='B0'
   for step,x in enumerate(order,1):
    active.add(x);after=lookup[frozenset(active)];orders.append(dict(graph=g,order=order,step=step,switch=x,before=before,after=after,stage_speedup=times[g,before]/times[g,after],before_cb_bytes=cb[g,before],after_cb_bytes=cb[g,after]));before=after
 csvwrite(O/'subset_times.csv',rows);csvwrite(O/'switch_pairs.csv',pairs);csvwrite(O/'switch_ranges.csv',summary);csvwrite(O/'order_steps.csv',orders)
 csvwrite(O/'profile_checks.csv',[{k:x[k] for k in ('graph','subset','count_exact','candidate_exact','candidates','l1_bytes')} for x in profiles])
 lines=['# 작업6 TRUST 네 스위치의 순서 의존성','',f"완료: {d['finished_at']}. **80/80셀 통과, 실패0**(profile20 + timing60). 실행 PID{d['pid']}, 시작 {d['started_at']}. 커널 변경 없음. `new_paper/`는 수정하지 않았다.",'','## 유효 정의와 대조 조건','','P=가지치기, H=open-addressing hash, S=정확 범위 공급과 page 1 KiB→16 KiB 변경, W=4-wide probe다. 기존 구현에서 **W는 H와 S 모두를 요구**한다. 따라서 유효 부분집합은10개, 전체 적용 순서는8개다. 원래 요청의 HW와 PHW는 `lookup_width==1 or (direct and hash_oa)` 제약과 DIRECT 분기 안의4-wide 구현 때문에 제외했다. assertion만 제거하거나 커널을 바꾸지 않았다. 이전12개 계획은 `gap/order-dependence/FEASIBILITY.json` 등에 보존했다.','','B0/B1/B2/B3/B4는 각각 ∅/P/PH/PHS/PHSW다. 다섯 anchor를 포함한 모든10개를 같은 block 안에서 새로 측정했다. 110코어×2 DM, hash-mix0, row/col cache16/64 KiB, hash16384, bucket cap100, META_STAGE64, arena64 KiB, chunk1048576 KiB로 기존 분해 설정을 유지했다. 실행기는 기존 `gap/run_trust_gap.py + host 전용 검증 어댑터 `gap/order-dependence/original_host.py``; 입력/runner/kernel SHA는 PLAN.json과 REFERENCE_CHECKS.json에 보존했다.','','각 셀 새 프로세스, timing warmup1+측정3, seed20261022+block으로20개 그래프·부분집합 조합을 섞은3block. 대표값은 block 중앙값의 중앙값이다. PROFILE은 profile에서만 켰다. Count 경계는 launch+sync+device reduction+작은 readback이다. 원자료와 엔진 전체 검증 readback은 시간에서 제외한다.','','기존 B1 원자료에는 후보 총계만 있어 모든 P 포함 profile의 합계를 기존 B1과 정확히 대조했다. 엔진별 후보는 동일 가지치기 경로인 기존 B2의220-engine 벡터와, P 없는 후보는 기존 B0 벡터와 정확히 대조했다. 모든 profile/timing은 기존 B0 또는 검증된 동일 구성 profile의220-engine count와 metadata110-core CPU oracle를 확인했다. profile20셀을 전부 통과한 뒤 timing을 시작했다.','','## 부분집합별 시간','','|부분집합|com-LJ (s)|com-Orkut (s)|CB KiB/core|','|---|---:|---:|---:|']
 for s in SUBSETS:
  assert cb['comlj',s]==cb['orkut',s]
  lines.append(f"|{'∅ (B0)' if s=='B0' else s}|{times['comlj',s]:.6f}|{times['orkut',s]:.6f}|{cb['comlj',s]/1024:g}|")
 lines+=['','## 스위치를 추가하는 모든 유효 쌍','','배수=T(A)/T(A∪{x}); 1보다 작으면 손해다. 아래 최소·중앙·최대는 해당 그래프에서 유효한 모든 추가 위치를 집계했다. S는 공급뿐 아니라 페이지 크기도 바꾸며, H/S가 CB 할당도 바꾸므로 순수 단일 명령의 인과 효과로 해석하지 않는다. 각 쌍의 전후 CB는 CSV에 기록했다.','','|그래프|스위치|쌍 수|최소|중앙|최대|범위(최대−최소)|최소 쌍|최대 쌍|','|---|---|---:|---:|---:|---:|---:|---|---|']
 for x in summary:lines.append(f"|{x['graph']}|{x['switch']}|{x['pairs']}|{x['min_speedup']:.3f}|{x['median_speedup']:.3f}|{x['max_speedup']:.3f}|{x['range_speedup']:.3f}|{x['min_pair']}|{x['max_pair']}|")
 lines+=['','## 유효8개 적용 순서','','각 단계는 바로 앞 부분집합 대비 배수다. 단계별 배수를 서로 다른 구성/그래프에서 곱해 개선을 주장하지 않는다. 동일한 B0와 PHSW를 잇는 순서들은 시작·끝이 같으며, 아래는 중간 단계에서 효과 배분이 어떻게 달라지는지를 보여준다.','','|그래프|순서|1단계|2단계|3단계|4단계|','|---|---|---:|---:|---:|---:|']
 for g in ('comlj','orkut'):
  for order in ORDERS:
   z=[x for x in orders if x['graph']==g and x['order']==order];lines.append('|'+g+'|'+order+'|'+'|'.join(f"{x['stage_speedup']:.3f}" for x in z)+'|')
 lines+=['','## 해석과 한계','','기존 누적 분해의 P→H→S→W는 유효한 한 경로다. 이번 대조는 같은 최종 구현에도 각 기능에 배분되는 이득이 선행 기능에 따라 달라지는지를 전체 유효 쌍에서 확인한다. W는 H·S가 먼저 있어야 하므로 네 스위치가 완전히 독립적인4요인 실험은 아니다. 두 그래프에서의 결과이며 다른 그래프로 일반화하지 않는다. 기존 분해 원자료와 이번 재측정값은 별도 cohort로 유지한다. 최초 order-dependence-v1은 최근 multiply-shift runner로 실행되어 source_count/max_bin 및 output 초기화 처리가 역사적 분해 커널과 달랐다. 해당 실행을 중단하지 않고 원자료를 별도로 보존했으며 본 표에는 포함하지 않았다. 최종 original-v2는 원래 커널 SHA를 고정하고 host의 CLI·원자료 저장·엔진별 검증만 추가했다(HOST_ONLY.diff). 생성 accessor, 커널 생성 구간, 측정 구간이 원본과 동일함을 검사했다. PROFILE=0은 원래 분해 커널 그대로이며 기존 source_count/max_bin 진단 동작까지 유지한다.','','산출물: `gap/order-dependence-original-v2/`의 `subset_times.csv`, `switch_pairs.csv`, `switch_ranges.csv`, `order_steps.csv`, `profile_checks.csv`, `PLAN.json`, `status.json`, 각 셀 원자료. 8개 순서는 기준 PHSW를 포함한다.']
 doc.write_text('\n'.join(lines)+'\n')
 (O/'ANALYSIS_COMPLETE.json').write_text(json.dumps(dict(status='complete',passed_cells=80,failed_cells=0,subsets=20,valid_pairs=len(pairs),orders=16,order_steps=len(orders)),indent=2)+'\n')
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--doc',type=Path,required=True);a=ap.parse_args();analyze(a.out,a.doc)
