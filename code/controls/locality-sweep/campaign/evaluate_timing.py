"""완료된 task38 timing만 집계한다. 장치 접근·재적합 없음."""
from pathlib import Path
import json,hashlib,csv,statistics,math,datetime
P=Path(__file__).resolve().parent;M=P.parents[2]/'model';O=P/'analysis-v1'
rd=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def wr(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
def csvout(p,rows):
 with p.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def main():
 complete=rd(P/'timing-v1/COMPLETE.json');assert complete['status']=='pass' and complete['timing_cells']==138
 pred=rd(M/'prediction-task38.json');fit=rd(M/'fit.json');auth=rd(P/'TIMING_AUTHORIZATION.json')
 for n,h in auth['files'].items():assert sha(M/n)==h
 assert fit['M1']['coef']==dict(a=pred['a'],b=pred['b'])
 cp=rd(P/'PREDICTION_REQUIRED.json');assert sha(P/cp['correctness'])==auth['correctness_sha256']
 O.mkdir(exist_ok=False);cells=[];by={}
 for r in complete['records']:
  f=P/r['summary'];assert sha(f)==r['summary_sha256'];s=rd(f);assert s['status']=='pass' and s['counters']==0 and s['warmup_runs']==1 and s['measured_runs']==3 and s['per_owner_exact']
  v=f.parent/'TIMING_VALIDATION.json';assert sha(v)==r['validation_sha256'];d=rd(v);assert d['status']=='pass' and d['cb_plan_exact']
  for x in d['repeats']:
   raw=f.parent/(('raw' if r['variant']=='L6' else 'result')+f"-{x['repeat']}.npy");assert sha(raw)==x['raw_sha256'] and x['owner_exact'] and x['total_exact']
  assert len(d['repeats'])==4
  vals=s['samples_s'];med=statistics.median(vals);assert med==s['median_s']==r['median_s']
  key=(r['graph'],r['family'],r['variant']);by.setdefault(key,{})[r['block']]=med
  cells.append(dict(block=r['block'],index=r['index'],graph=r['graph'],family=r['family'],variant=r['variant'],median_s=med,sample1_s=vals[0],sample2_s=vals[1],sample3_s=vals[2],summary=r['summary'],summary_sha256=r['summary_sha256'],validation_sha256=r['validation_sha256'],cb_bytes=d['cb_bytes']))
 assert len(cells)==138 and len(by)==46 and all(set(v)=={0,1,2} for v in by.values())
 med={k:statistics.median(v.values()) for k,v in by.items()}
 aggregate=[dict(graph=k[0],family=k[1],variant=k[2],block0_s=v[0],block1_s=v[1],block2_s=v[2],median_of_block_medians_s=med[k]) for k,v in sorted(by.items())]
 classify=lambda x:'gain' if x>pred['gain'] else 'loss' if x<pred['loss'] else 'neutral'
 qs=list(csv.DictReader((P/'final-scope-v1/REQUEST_RATIOS_LOCALITY.csv').open()));A=[]
 for q in qs:
  p=float(q['p']);fam=q['family'];g=q['graph'];rr=float(q['Q_D1_over_D0']);pr=next(r for r in pred['A_locality'] if float(r['p'])==p and r['family']==fam)
  t0=med[(g,fam,'D0')];t1=med[(g,fam,'D1')];s=t0/t1;y=math.log(s);yh=pred['a']+pred['b']*math.log(rr)
  A.append(dict(p=p,graph=g,family=fam,Q_D0=int(q['Q_D0']),Q_D1=int(q['Q_D1']),request_ratio=rr,D0_ms=t0*1000,D1_ms=t1*1000,speedup=s,measured_direction=classify(s),M1_registered_speedup=pr['predicted_speedup'],M1_exact_speedup=math.exp(yh),M1_direction=pr['direction'],direction_match=classify(s)==pr['direction'],M1_abs_log_error=abs(y-yh),M1_rounded_abs_log_error=abs(y-math.log(pr['predicted_speedup'])),constant_abs_log_error=abs(y-fit['null_mean_y']),block0_speedup=by[(g,fam,'D0')][0]/by[(g,fam,'D1')][0],block1_speedup=by[(g,fam,'D0')][1]/by[(g,fam,'D1')][1],block2_speedup=by[(g,fam,'D0')][2]/by[(g,fam,'D1')][2]))
 A.sort(key=lambda r:(r['p'],r['family']))
 A2=[]
 for fam in ['wetric','tricore']:
  rows=sorted([r for r in A if r['family']==fam],key=lambda r:r['p']);pairs=[dict(p_from=a['p'],p_to=b['p'],from_speedup=a['speedup'],to_speedup=b['speedup'],strict_increase=b['speedup']>a['speedup']) for a,b in zip(rows,rows[1:])];A2.append(dict(family=fam,passed=all(r['strict_increase'] for r in pairs),adjacent_pairs=pairs))
 C=[]
 for g in pred['C_handoff']['graphs']:
  t0=med[(g,'trust','L5-T')];t1=med[(g,'trust','L6')];sp=t0/t1
  C.append(dict(graph=g,skew=g.split('-')[0],edge_factor=int(g.split('ef')[1]),L5_T_ms=t0*1000,L6_ms=t1*1000,speedup=sp,direction=classify(sp),block0_speedup=by[(g,'trust','L5-T')][0]/by[(g,'trust','L6')][0],block1_speedup=by[(g,'trust','L5-T')][1]/by[(g,'trust','L6')][1],block2_speedup=by[(g,'trust','L5-T')][2]/by[(g,'trust','L6')][2]))
 C3=[]
 for skew in ['S0','S1','S2']:
  rows=sorted([r for r in C if r['skew']==skew],key=lambda r:r['edge_factor']);C3.append(dict(skew=skew,passed=rows[0]['speedup']<rows[1]['speedup']<rows[2]['speedup'],speedups=[r['speedup'] for r in rows]))
 mae=statistics.mean(r['M1_abs_log_error'] for r in A);null=statistics.mean(r['constant_abs_log_error'] for r in A)
 score=dict(A1=dict(correct=sum(r['direction_match'] for r in A),total=14,passed=all(r['direction_match'] for r in A),mismatches=[dict(p=r['p'],family=r['family'],predicted=r['M1_direction'],observed=r['measured_direction']) for r in A if not r['direction_match']]),A2=dict(passed=all(r['passed'] for r in A2),families=A2),A3=dict(type='descriptive_error_comparison_no_pass_target',M1_mean_absolute_log_error=mae,constant_gain_mean_absolute_log_error=null,constant_gain_speedup=math.exp(fit['null_mean_y']),constant_log_gain=fit['null_mean_y'],constant_source='fit.json null_mean_y from original training data; no task38 refit',M1_lower_error=mae<null,rounded_registered_prediction_mean_absolute_log_error=statistics.mean(r['M1_rounded_abs_log_error'] for r in A)),C1=dict(passed=all(r['direction']=='gain' for r in C if r['edge_factor']==64),correct=sum(r['direction']=='gain' for r in C if r['edge_factor']==64),total=3),C2=dict(passed=all(r['direction']=='loss' for r in C if r['edge_factor']==4),correct=sum(r['direction']=='loss' for r in C if r['edge_factor']==4),total=3),C3=dict(passed=all(r['passed'] for r in C3),skews=C3))
 provenance={str(f.relative_to(P.parents[2])):sha(f) for f in [M/'PREREGISTRATION-24.md',M/'prediction-task38.json',M/'fit.json',P/'TIMING_AUTHORIZATION.json',P/'PREDICTION_REQUIRED.json',P/'timing-v1/COMPLETE.json',P/'final-scope-v1/CORRECTNESS_COMPLETE.json',P/'timing-code/KERNEL_EXACT.json']}
 result=dict(task=38,status='complete',timing_cells=138,passed=138,failed=0,graphs=16,variants_per_block=46,blocks=3,aggregation='median of 3 within-cell samples, then median of 3 block medians; speedup = reference median / variant median',direction_rule='gain > 1.03; loss < 0.97; neutral otherwise',preregistration_commit='c28af273',score=score,A_locality=A,C_handoff=C,provenance_sha256=provenance,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
 csvout(O/'TIMING_CELLS.csv',cells);csvout(O/'TIMING_MEDIANS.csv',aggregate);csvout(O/'LOCALITY.csv',A);csvout(O/'HANDOFF.csv',C)
 wr(M/'eval-task38.json',result)
 lines=['# 작업38: 합성 그래프 sweep 결과','','138/138 timing 셀 통과, 실패 0. 지역성 28구성·그래프 + 실험 C 18구성·그래프를 3블록 측정했다. R-MAT A의 54개 profile은 보존했고 이번 timing에서 제외했다.','','## 프로토콜과 집계','','커밋 c28af273의 사전 등록과 correctness checkpoint 8dce30cc…7a9e66f를 확인한 뒤 실행했다. 각 셀 새 프로세스, warmup 1회 + 측정 3회, counters off, 블록당 전체 46셀을 Random(20261022+block)으로 셔플했다. Count 경계는 기존 runner의 launch+synchronize+device reduction+작은 readback이다. 업로드와 전체 owner 검증 readback은 시간 경계 밖이다. 매 반복 total 및 owner count를 profile 기준과 exact 비교했고 runtime CB도 동일했다. 공유 lock과 모니터링 점유 대기(1초, 최대120초)를 사용했다.','','각 셀의 3회 중앙값을 구한 뒤 3블록 중앙값의 중앙값을 사용한다. speedup은 기준 시간/변형 시간이다. gain >1.03, loss <0.97, 나머지 neutral. 블록별 비율도 CSV/JSON에 보존한다.','','## 예측 채점','',f"- A1 방향: {score['A1']['correct']}/14 일치. 전체 일치 {'통과' if score['A1']['passed'] else ' 실패'}.",f"- A2 p에 따른 단조 증가: "+', '.join(r['family']+(' 통과' if r['passed'] else ' 실패') for r in A2)+'.',f"- A3 평균 절대 자연로그 오차: M1 {mae:.6f}, 상수 gain {null:.6f}. M1의 오차가 {'작다' if mae<null else '작지 않다'}. A3는 정해진 합격 기준 없이 오차를 보고하는 항목이다.",f"- C1 ef64 모두 gain: {score['C1']['correct']}/3, {'통과' if score['C1']['passed'] else ' 실패'}.",f"- C2 ef4 모두 loss: {score['C2']['correct']}/3, {'통과' if score['C2']['passed'] else ' 실패'}.",'- C3 각 skew에서 ef4 < ef16 < ef64: '+', '.join(r['skew']+(' 통과' if r['passed'] else ' 실패') for r in C3)+'.','',f"상수 gain은 기존 PREREGISTRATION.md §4의 null 모델, 즉 원래 학습 집합의 평균 log gain {fit['null_mean_y']:.15f}(speedup {math.exp(fit['null_mean_y']):.6f})다. task38 자료로 재적합하지 않았다. M1 오차는 동결 a,b와 정확한 profile 요청 비로 계산했다. 표의 M1 값과 방향은 사전 등록 JSON 값이며, 반올림된 등록값의 오차도 eval JSON에 별도 보존했다.",'','## 지역성 sweep','','| p | 계열 | Q_D1/Q_D0 | D0 ms | D1 ms | 측정 speedup | 측정 방향 | M1 등록값 | M1 방향 | 일치 |','|---:|---|---:|---:|---:|---:|---|---:|---|---|']
 for r in A:lines.append(f"| {r['p']:g} | {r['family']} | {r['request_ratio']:.6f} | {r['D0_ms']:.6f} | {r['D1_ms']:.6f} | {r['speedup']:.6f} | {r['measured_direction']} | {r['M1_registered_speedup']:.3f} | {r['M1_direction']} | {'O' if r['direction_match'] else 'X'} |")
 lines+=['','## R-MAT TRISC rung','','| 그래프 | L5-T ms | L6 ms | L5-T/L6 speedup | 방향 |','|---|---:|---:|---:|---|']
 for r in C:lines.append(f"| {r['graph']} | {r['L5_T_ms']:.6f} | {r['L6_ms']:.6f} | {r['speedup']:.6f} | {r['direction']} |")
 lines+=['','## 판정의 범위','','지역성 조작은 같은 무방향 격자의 ID 일부만 순열로 바꾸고 기존 degree 방향화를 다시 적용했다. 삼각형 수는 모두 2,093,058이다. 동률 ID 순서에 따라 forward 후보 작업량도 달라지므로 후보 집합까지 고정된 개입이라고 주장하지 않는다. CPU oracle 총합 및 D0/D1 owner·후보 count 벡터 일치를 통과한 동일 입력 내 비교다. 실험 C는 기존 CPU replay·장치 exact 관문을 통과한 18셀을 재사용했다. 서로 다른 요청 수·기법의 예측 결과이지 전체 그래프 분포에 대한 보편적 손익분기 증명은 아니다.','','## 원자료와 SHA','','원자료: `optimization_20261022/gap/task38-sweep-v1/timing-v1/` (셀별 summary, samples, runtime CB, 4회 count 결과, TIMING_VALIDATION). 집계 CSV와 재현 코드: `analysis-v1/`, `evaluate_timing.py`. 셀별 summary·검증 SHA는 TIMING_CELLS.csv, 입력·profile SHA는 final-scope-v1/profiles.json에 있다. 원고는 수정하지 않았다.','']
 for path,h in provenance.items():lines.append(f'- `{path}`: `{h}`')
 (M/'RESULTS-task38.md').write_text('\n'.join(lines)+'\n')
 wr(O/'COMPLETE.json',dict(status='pass',evaluation_sha256=sha(M/'eval-task38.json'),report_sha256=sha(M/'RESULTS-task38.md'),timing_complete_sha256=sha(P/'timing-v1/COMPLETE.json')))
 print(json.dumps(score,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
