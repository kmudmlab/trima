"""로컬 전용: 모든 셀이 완료·동기화된 후 등록된 일곱 예측을 그대로 채점."""
from pathlib import Path
import json,hashlib,statistics,csv,datetime,math
P=Path(__file__).resolve().parent;G=P.parent;M=P.parents[2]/'model'
read=lambda p:json.loads(p.read_bytes())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n');t.replace(p)
def main():
 complete=read(P/'timing/COMPLETE.json');assert complete['status']=='complete' and complete['passed']==210 and complete['failed']==0
 auth=read(P/'TIMING_AUTHORIZATION.json');pred=read(M/'prediction-task36.json')
 assert sha(M/'prediction-task36.json')==auth['prediction_sha256'] and sha(M/'PREREGISTRATION-23.md')==auth['prereg_sha256']
 graphs=[r['graph'] for r in read(P/'jobs.json') if not r['fixture']];groups={};provenance=[]
 for r in complete['records']:
  f=P/'timing'/r['name']/'summary.json';s=read(f);assert sha(f)==r['summary_sha256']
  assert s['status']=='pass' and s['per_owner_exact'] and s['counters']==0 and s['warmup_runs']==1 and s['measured_runs']==3
  if r.get('kind')=='empty':
   prior=P/'device-correctness-v1'/('empty-'+r['variant']);sources=sorted(f.parent.glob('*.cpp'))
   assert len(sources)==(2 if r['variant']=='B' else 3)
   for source in sources:assert source.read_bytes()==(prior/source.name).read_bytes(),('empty kernel body mismatch',source)
  ts=s['samples_s'];assert len(ts)==3 and all(math.isfinite(t) and t>0 for t in ts)
  med=statistics.median(ts);assert med==s['median_s'];key=(r['graph'],r['variant']);groups.setdefault(key,{})[r['block']]=med
  provenance.append(dict(graph=r['graph'],variant=r['variant'],block=r['block'],path=str(f.relative_to(P.parents[3])),sha256=sha(f),samples_s=ts,block_median_s=med))
 assert len(groups)==70 and all(set(x)=={0,1,2} for x in groups.values())
 ts={k:statistics.median(v.values()) for k,v in groups.items()};rows=[]
 for g in graphs:
  r=dict(graph=g,**{v+'_s':ts[g,v] for v in ['L2','L3-p1k','L2-p16k','L3']})
  for name,a,b in [('L2_to_L3-p1k','L2','L3-p1k'),('L2_to_L2-p16k','L2','L2-p16k'),('L3-p1k_to_L3','L3-p1k','L3'),('L2_to_L3','L2','L3')]:r[name]=ts[g,a]/ts[g,b]
  rows.append(r)
 by={r['graph']:r for r in rows};scores=[]
 def add(i,rule,checks,passed=None):
  scores.append(dict(id=i,rule=rule,passed=all(x['passed'] for x in checks) if passed is None else passed,checks=checks))
 small=pred['predictions'][0]['loss_graphs'];gain=pred['gain'];loss=pred['loss']
 add(1,'지정한 네 그래프에서 L2/L3-p1k < 0.97',[dict(graph=g,ratio=by[g]['L2_to_L3-p1k'],passed=by[g]['L2_to_L3-p1k']<loss) for g in small])
 add(2,'같은 네 그래프에서 (L2/L3-p1k) <= 1.03*(L2/L3)',[dict(graph=g,left=by[g]['L2_to_L3-p1k'],right=1.03*by[g]['L2_to_L3'],passed=by[g]['L2_to_L3-p1k']<=1.03*by[g]['L2_to_L3']) for g in small])
 checks=[dict(graph=g,ratio=by[g]['L2_to_L2-p16k'],passed=loss<=by[g]['L2_to_L2-p16k']<=gain) for g in graphs]
 add(3,'17개 중 14개 이상에서 0.97 <= L2/L2-p16k <= 1.03',checks,sum(x['passed'] for x in checks)>=14)
 add(4,'모든 그래프에서 L3-p1k/L3 >= 0.97',[dict(graph=g,ratio=by[g]['L3-p1k_to_L3'],passed=by[g]['L3-p1k_to_L3']>=loss) for g in graphs])
 add(5,'지정한 여섯 그래프에서 L2/L3-p1k > 1.03',[dict(graph=g,ratio=by[g]['L2_to_L3-p1k'],passed=by[g]['L2_to_L3-p1k']>gain) for g in pred['predictions'][4]['gain_graphs']])
 eb,el=ts['empty','B'],ts['empty','L7'];add(6,'empty L7 > empty B',[dict(B_s=eb,L7_s=el,passed=el>eb)])
 final=G/'task35-final-v1';fc=read(final/'timing/COMPLETE.json');finalrefs={};fprovenance=[]
 for g in ['fb','comlj']:
  vv=[]
  for r in fc['records']:
   if r['status']=='pass' and r['graph']==g and r['variant']=='L7' and r['group']=='A':
    f=final/r['cell']/'summary.json';s=read(f);assert sha(f)==r['summary_sha256'];vv.append(statistics.median(s['samples_s']));fprovenance.append(dict(graph=g,block=r['block'],path=str(f.relative_to(P.parents[3])),sha256=sha(f),block_median_s=vv[-1]))
  assert len(vv)==3;finalrefs[g]=statistics.median(vv)
 add(7,'empty L7 >= 0.30*L7(fb) 그리고 <= 0.05*L7(com-LJ)',[dict(graph='fb',empty_to_count=el/finalrefs['fb'],limit=0.30,comparison='>=',passed=el>=0.30*finalrefs['fb']),dict(graph='comlj',empty_to_count=el/finalrefs['comlj'],limit=0.05,comparison='<=',passed=el<=0.05*finalrefs['comlj'])])
 cb=read(P/'CB_RUNTIME_RECOUNT.json')
 out=dict(status='complete',registered_commit='b807969b',correctness_sha256=auth['correctness_sha256'],prereg_sha256=auth['prereg_sha256'],prediction_sha256=auth['prediction_sha256'],timing_complete_sha256=sha(P/'timing/COMPLETE.json'),passed_cells=210,failed_cells=0,scored_predictions=7,passed_predictions=sum(x['passed'] for x in scores),predictions=scores,graph_times_and_ratios=rows,empty_seconds=dict(B=eb,L7=el),aggregation='median of three block medians; each block median uses three measured runs after one warmup',provenance=provenance,prediction7_L7_source=fprovenance,runtime_cb=cb,updated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
 with (P/'TIMING_TABLE.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 with (P/'EMPTY_TIMING.csv').open('w',newline='') as f:
  w=csv.writer(f);w.writerow(['path','block0_median_s','block1_median_s','block2_median_s','median_of_blocks_s'])
  for v in ['B','L7']:w.writerow([v,*[groups['empty',v][b] for b in range(3)],ts['empty',v]])
 lines=['# 작업36 결과: 페이지 2×2와 빈 작업 Count 고정비','',f'210/210셀 통과, 실패 0. 등록 b807969b의 예측 **{out["passed_predictions"]}/7개 충족**. 각 예측은 사전에 지정한 그래프와 부등식을 그대로 적용했다. 그래프별 일부 조건만 맞은 복합 예측은 전체 충족으로 세지 않았다.','',f'정확성 checkpoint: `{auth["correctness_sha256"]}`. 원자료: `optimization_20261022/gap/review-response-v1/timing/`; 파일별 SHA와 반복 값은 `eval-task36.json`에 기록했다.','', '셀마다 fresh process, warmup 1+측정 3, 3블록, seed=20261022+block, counters off. 각 블록의 page 68개와 empty 2개를 함께 셔플했다. 집계는 block 중앙값의 중앙값이다. Count는 launch+synchronize+기존 reducer와 작은 readback이며, upload·전체 검증 readback·CB discovery·empty poison은 제외했다. 모든 반복에서 total/owner count를 검사했다.','', '## 그래프별 시간과 비율','', '시간 단위 ms. 비율은 앞 구성 시간/뒤 구성 시간이며 1보다 크면 뒤 구성이 빠르다. DIRECT의 arena/stage 때문에 cache와 range의 CB 예약은 같지 않다. cache 용량은 page 크기와 무관하게 row16/col64 KiB로 고정했다.','', '| 그래프 | L2 | L3-p1k | L2-p16k | L3 | L2→L3-p1k | L2→L2-p16k | L3-p1k→L3 | L2→L3 |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
 for r in rows:lines.append('| '+r['graph']+' | '+' | '.join(f'{r[v+"_s"]*1000:.6f}' for v in ['L2','L3-p1k','L2-p16k','L3'])+' | '+' | '.join(f'{r[k]:.6f}' for k in ['L2_to_L3-p1k','L2_to_L2-p16k','L3-p1k_to_L3','L2_to_L3'])+' |')
 lines+=['','## 빈 작업 경로','', '| 경로 | block0 (ms) | block1 (ms) | block2 (ms) | 중앙값 (ms) |','|---|---:|---:|---:|---:|']
 for v in ['B','L7']:lines.append('| '+v+' | '+' | '.join(f'{groups["empty",v][b]*1000:.6f}' for b in range(3))+f' | {ts["empty",v]*1000:.6f} |')
 lines+=['','Facebook CB 배치(B448 KiB, L7 832 KiB)를 사용한 빈 작업 하한이다. ring/ACK·hash·tail preload는 하지 않으므로 실제 그래프 Count의 모든 고정 비용이나 모든 CB 배치의 비용을 대신하지 않는다. 커널 생성 본문은 검증 사본과 동일(TIMING_HOST_PROOF.json), 시간 경계만 추가했다.','', '## 사전 등록 예측 채점','', '| 번호 | 판정 | 조건별 확인 |','|---|---|---|']
 for x in scores:
  details=[]
  for c in x['checks']:
   vals=', '.join(f'{k}={v:.6g}' if isinstance(v,float) else f'{k}={v}' for k,v in c.items() if k!='passed');details.append(vals+(' (충족)' if c['passed'] else ' (미충족)'))
  lines.append(f'| {x["id"]} | '+('충족' if x['passed'] else '미충족')+' | '+'; '.join(details)+' |')
 lines+=['',f'예측7의 L7 분모는 등록 근거인 task35-final-v1 A/L7의 3블록 중앙값: Facebook {finalrefs["fb"]*1000:.6f} ms, com-LJ {finalrefs["comlj"]*1000:.6f} ms. 새 empty 측정과는 별도 캠페인이며 이 출처 차이를 숨기지 않는다.','', '## 실행·환경 기록','', '측정 제어기·runner 변경은 review-response-v1의 새 파일로 제한했다. 배포 중 상대 경로 중첩 오류는 장치 실행 전에 바로잡았으며 TIMING_PREPARATION.md에 기록했다. 점유 대기는 각 셀 device-wait*.json에 PID와 재확인 횟수를 보존한다. 원고는 수정하지 않았다.','', '## Runtime CB 재집계','',cb['markdown']]
 write(M/'eval-task36.json',out);t=M/'RESULTS-task36.md.tmp';t.write_text('\n'.join(lines)+'\n');t.replace(M/'RESULTS-task36.md')
 write(P/'POSTPROCESS_COMPLETE.json',dict(status='complete',passed_cells=210,passed_predictions=out['passed_predictions'],results_sha256=sha(M/'RESULTS-task36.md'),eval_sha256=sha(M/'eval-task36.json'),utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
 print(json.dumps(dict(status='complete',cells=210,predictions_passed=out['passed_predictions'])))
if __name__=='__main__':main()
