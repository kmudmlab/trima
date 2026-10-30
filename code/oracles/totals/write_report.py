#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict,Counter
import json,csv,datetime
E=Path(__file__).resolve().parents[1];O=Path(__file__).resolve().parent
A=json.loads((O/'AUDIT.json').read_text());T=A['totals'];D=json.loads((O/'inventory.json').read_text());ROWS=list(csv.DictReader((O/'campaign_totals.csv').open()))
def link(f):return f'[{f}](final-totals-v1/{f})'
def tab(headers,rows):return ['|'+'|'.join(headers)+'|','|'+'|'.join('---' for _ in headers)+'|']+['|'+'|'.join(str(v) for v in r)+'|' for r in rows]
names={'initial-port':'초기 포팅/기준선/용량','optimization':'초기 최적화/추가 실험','gap-bottomup':'TRUST 누적 분해','gap-topdown':'TriMA 기능 제거','gap-coop':'TriMA/notrisc 협력','gap-direct':'직접 공급/fixture','gap-nocounters':'카운터 off 재측정','gap-smoke':'gap smoke','hash-mix':'초기 hash-mix (장치 leaf 누락)','multiply-shift-v1':'multiply-shift fixture','multiply-shift-v2':'multiply-shift 통제/TRIMA 0·1·2','aux-rowptr-device':'작업19 aux-rowptr','aux-rowptr-counterfix':'작업19 IO 수정 profile','trima-final':'작업20 최종 TriMA','task13':'작업13 학습·검증/도로망 복구','polak':'Polak','locality':'도로망 공급 대조','trisc':'StepTC TRISC','suite-v1':'suite-v1','order-dependence-superseded':'순서 의존성 v1 (최종 표 제외)','order-dependence-final':'순서 의존성 original-v2'}
lines=['# 최종 정확성·CB·그래프 수 집계','',f'작성: {datetime.datetime.now().astimezone().isoformat(timespec="seconds")}. 로컬 보존 기록만 읽고 집계했다. TT·bear 접속, 장치 실행, 새 oracle/replay 실행, `new_paper/` 수정은 하지 않았다. NoC와 GPU 캠페인은 이번 TT 집계에서 제외했다. 초기 BTC/ToT 탐색 실험은 초기 포팅·최적화에 포함했다.','','## 먼저 적용할 범위 제한','', '**이 문서의 합계는 로컬에서 셀별 확인 가능한 하한이며, 전체 연구의 완전한 실행 총계가 아니다.** 초기 hash-mix 포팅 대조는 상위 체인에 14개 그래프의 rc0 종료가 있지만 해당 leaf 결과가 로컬에 없다. 당시 계획 596셀을 실제 통과로 더하지 않았다. WebCC source baseline 복구도 상위 rc0만 있고 해당 leaf 결과가 없다. 네트워크 조회 금지 지시에 따라 기록 누락을 그대로 남겼다. 상세는 '+link('evidence_gaps.csv')+'다.','','후속 multiply-shift-v2에는 mix0/1/2의 새 대조 원자료가 있으므로 그 셀들은 정상 포함했다. 초기 hash-mix가 “0회 실행되었다”는 뜻이 아니다. 오래된 `HASH_MIX_RESULTS.md`의 대기 상태·계획 숫자도 측정 결과로 사용하지 않았다.','','## 합계와 단위','',f"로컬 확인: **CPU oracle/의미 검사 {T['cpu_oracle_semantic_pass']:,}건**, **장치 fixture {T['fixture_pass']:,}셀**, **실그래프 profile {T['profile_pass']:,}셀 + timing {T['timing_pass']:,}셀 = {T['profile_pass']+T['timing_pass']:,}셀** 통과. 장치 통과 합계는 **{T['fixture_pass']+T['profile_pass']+T['timing_pass']:,}셀**이다.", '',f"별도 단위: CPU ring/배치/slot/카운터/layout 검사 {T['cpu_supporting_pass']}건, 입력 준비 검사 {T['cpu_preparation_pass']}건, IO replay 비교 {T['cpu_io_replay_pass']}건. 이들을 oracle 검사나 장치 셀 수에 섞지 않았다. matrix empty fast path 1건은 장치 fixture에서 제외했다.",'', '초기 pilot/탐색의 반복 수와 현재 표준 프로토콜은 다르므로 이 통과 총계를 모두 동일한3block timing 실험으로 표현하지 않는다. 셀은 `--out`의 실제 실행 디렉터리 하나다. warmup/반복 측정/CB readback 파일 수를 셀 수에 곱하지 않았다. 같은 출력 디렉터리를 가리키는 상위 status·재개 기록·로컬 사본은 한 셀로 합쳤다. 출력 디렉터리가 다른 실제 재측정은 별도 실행이므로 포함한다. 원래 순서 의존성 v1 80셀은 검증 통과 이력에 포함하되 최종 논문 성능 표에서 제외된 cohort로 명시한다. 이를 제외한 장치 통과 하한은 '+f"{T['fixture_pass']+T['profile_pass']+T['timing_pass']-80:,}셀"+'이다.','','CPU 수는 저장된 각 실행 보고서의 검사 건수다. 고유 그래프 수·서로 다른 정리의 수가 아니다. `CPU_APPROVED.json`, 최종 audit 합계, 복사본은 원본 검사 보고서와 중복해서 더하지 않았다. opt0/1/2는 동일한 정답 JSON을 만들더라도 별도 설정에서 실행한 보고서이므로 구분한다. Polak 실패 보고서에 명시된 실패 전 완료 240+246검사는 포함했으며, 실패 전 미완료 검사는 포함하지 않았다. 실패 보고서 전체를 제외한 완결 CPU oracle/의미 검사 보고서 합계는 '+f"{T['cpu_oracle_semantic_pass']-486:,}건"+'이다. 셀 내부에서 재사용한 기존 CPU oracle와 반복 `--cpu-check`는 새로운 독립 CPU 검사 보고서로 다시 더하지 않았다.','','## 캠페인별 표','', 'CPU=oracle/의미 검사. CPU가0이면 새 독립 보고서가 집계되지 않았다는 뜻이며, 기존 oracle를 사용하지 않았다는 뜻은 아니다. 지원 검사·준비·IO replay·단계 실패는 CSV의 별도 열에 있다. “중단”은 승인된 시간 제한 중단, “미측정”은 명시적 생략이다.','']
rs=[]
for r in ROWS:
 if r['campaign']=='TOTAL_LOCAL_VERIFIED':continue
 rs.append([names.get(r['campaign'],r['campaign']),r['cpu_oracle_semantic_pass'],r['fixture_pass'],r['profile_pass'],r['timing_pass'],r['failed_cells'],r['interrupted_cells'],r['unmeasured_cells']])
rs.append(['로컬 확인 합계',T['cpu_oracle_semantic_pass'],T['fixture_pass'],T['profile_pass'],T['timing_pass'],T['failed_cells'],T['interrupted_cells'],T['unmeasured_cells']])
lines+=tab(['캠페인','CPU','fixture','profile','timing','실패','중단','미측정'],rs)
lines+=['', '행별 근거: '+link('cells.csv')+' · '+link('cpu_checks.csv')+' · '+link('campaign_totals.csv')+'. 요약 CSV 사본은 [FINAL_TOTALS.csv](FINAL_TOTALS.csv).','','## 실패·미측정 분류','','성공/실패/중단/미측정은 셀 장부 안에서 서로 겹치지 않는다. 아래 실행 전·캠페인 단계 실패와 IO 기록 결함은 별도 단위이므로 셀 실패 수와 합산하지 않는다.','']
lines+=tab(['분류','건수','의미'],[
['장치 실행기/빌드 실패 셀',3,'-Werror 1, host API 2. 검출된 triangle count 불일치가 원인은 아님'],['시간 제한 중단 셀',1,'WebCC StepTC D3 profile, 원자료 보존'],['명시적 시간 제한 미측정',39,'suite19 + multiply-shift-v2 20'],['장치 실행 전 셀 실패',1,'작업13 roadNet-PA 경로 None; 복구24셀은 통과 표에 포함'],['셀 생성 전 캠페인 단계 실패',2,'TriMA fb 경로 표현식, TRISC manifest 누락'],['CPU 단계 실패',3,'Polak2 + 도로망 준비1; 오류/복구 기록 보존'],['IO 카운터 비교 결함',34,'작업19 최초 CSV: count/candidate는 참, IO exact는 거짓. 수정 profile34/34 정확 일치']])
lines+=['','suite 정책의 D3 profile은 이미 중단1셀에 있으므로 정책 파일의20항목을 미측정20으로 다시 더하지 않았다. 따라서 suite는 중단1+순수 미측정19다. multiply-shift-v2의 생략5변형은 각 profile1+timing3=20셀로 펼쳤다. 성능 반례에 따른 일시 중지 및 stale 상위 running 상태는 count 실패로 세지 않았다. 기록에서 확인된 count 불일치 실패는0건이나, 누락된 전체 캠페인까지 “실패0”을 주장하지 않는다. 현행 실패는 수정/복구 후에도 과거 이력에서 삭제하지 않았다.','','분류별 셀 원장: '+link('failed_and_unmeasured.csv')+'; 실행 전·CPU 단계·IO 결함: '+link('incidents.csv')+'. 미측정 용량 초과로 명시된 TT 셀은 이번 로컬 장부에서0개다. 미시작 계획·누락 파일을 용량 미적용이나 성공으로 바꾸지 않았다.','','## 런타임 CB 할당','',f"장치 주소/readback으로 확인된 **{A['runtime_cb_cells']}셀, {A['runtime_cb_records']:,}기록**의 최대값은 **{A['max_runtime_cb_KiB']:g} KiB/core**다. 1,392 KiB/core 한도 초과 기록은 **0**이다. 반복별 `cb-allocation-*.json`과 StepTC TRISC의 `cb_discovery`/`cb-discovery.npy`를 사용했다. 주소·descriptor 합계를 교차 확인했다. 모든 저장 코어의 크기·구간 검사 기록은 [CB_READBACK_AUDIT.json](final-totals-v1/CB_READBACK_AUDIT.json)에 있다.",'',f"성공 실행의 host config/summary에 선언된 CB 최대는 별도로 **{A['max_host_declared_cb_KiB']:g} KiB/core**이며 이 값도 한도 이하다. 이 선언값을 장치에서 읽어 확인한 런타임 용량으로 격상하지 않는다. **모든 변형의 런타임 CB를 확인했다는 주장은 할 수 없다.**",'']
cb=list(csv.DictReader((O/'cb_variants.csv').open()));ct=[]
for camp in sorted({r['campaign'] for r in cb}):
 z=[r for r in cb if r['campaign']==camp];rt=[float(r['max_runtime_cb_KiB']) for r in z if r['max_runtime_cb_KiB']];h=[float(r['max_host_declared_cb_KiB']) for r in z if r['max_host_declared_cb_KiB']]
 ct.append([camp,sum(int(r['runtime_observed_cells']) for r in z),f'{max(rt):g}' if rt else '없음',f'{max(h):g}' if h else '없음'])
lines+=tab(['캠페인','런타임 확인 셀','런타임 최대 KiB/core','host 선언 최대 KiB/core'],ct)
missing=list(csv.DictReader((O/'cb_no_runtime_record.csv').open()));cl=Counter(r['evidence_class'] for r in missing)
lines+=['',f"전체 fixture까지 포함한 정확한 실행 설정 그룹 중 런타임 CB 기록이 전혀 없는 그룹은 **{len(missing)}개**다(host 선언만 {cl['host_declared_only']}개, 수치 기록도 없음 {cl['no_numeric_allocation_record']}개). 상세 목록은 "+link('cb_no_runtime_record.csv')+'에 캠페인·계열·변형 설정·셀 수·최대 선언값을 모두 실었다. 일부 셀만 런타임 기록이 있는 그룹의 누락 셀 수도 '+link('cb_variants.csv')+'에 별도 표시했다.','','런타임 반복별 원장: '+link('cb_runtime_records.csv')+'. 셀별 최대값: '+link('cells.csv')+'. 기존 suite 정적 용량 검사 목록: '+link('static_preflight_inventory.csv')+'; 이 파일의 `runtime_allocation_verified=false`는 당시 정적 검사 상태이며 후속 캠페인의 실제 런타임 기록을 대체하지 않는다.','','## 측정 그래프 수','','suite의 고유 그래프14개에 roadNet-PA/TX/CA3개를 더한 **17개**다. 여러 변형·block에 등장한 동일 그래프는 한 번 센다. profile과 timing의 그래프 수를 분리했다. 원자료가 없는 예전 WebCC source cohort는 그 cohort의 coverage에 넣지 않았다.','']
fr=list(csv.DictReader((O/'family_graphs.csv').open()));lines+=tab(['계열','suite','도로망','합집합'],[[r['family'],r['suite_graphs'],r['road_graphs'],r['graphs']] for r in fr])
# Readable paper variants, merging L0 profile runner with L0 timing anchor by recorded L, not raw host CLI defaults.
selected={'suite-v1','multiply-shift-v2','aux-rowptr-device','aux-rowptr-counterfix','trima-final','task13','polak','locality','order-dependence-final','trisc'}
variants=defaultdict(lambda:dict(profile=set(),timing=set(),configs=set()))
for c in D.values():
 if c['campaign'] not in selected or c['status']!='pass' or c['phase'] not in ('profile','timing'):continue
 cfg=c['config'];fam=c['family'];camp=c['campaign'];records=c['records'];r=records[-1] if records else {}
 mix=cfg.get('hash_mix',0)
 if camp=='order-dependence-final':label=r.get('subset',c['variant_label'])
 elif camp=='task13':label='L'+str(r.get('L',cfg.get('supply_threshold',0)))
 elif fam=='trima':label=f"mix{mix}/aux{cfg.get('aux_rowptr',0)}"+('/notrisc' if int(cfg.get('no_trisc',0)) else '')
 elif camp=='trisc':label=cfg.get('cell',c['variant_label'])
 elif fam=='trust':
  label='B4' if int(cfg.get('lookup_width',1))==4 else 'B3' if int(cfg.get('direct',0)) else 'B2' if int(cfg.get('hash_oa',0)) else 'B1' if int(cfg.get('prune',0)) else 'B0';label+=f'/mix{mix}'
 elif fam=='steptc':label=('D3' if int(cfg.get('lookup_width',1))==4 else 'D2')+f'/mix{mix}' if int(cfg.get('hash_oa',0)) else 'D1' if 'direct' in str(cfg.get('mode','')) else 'base'
 elif fam=='wetric':label='D5' if int(cfg.get('branchless',0)) else 'D1' if 'direct' in str(cfg.get('mode','')) else 'base'
 else:label='D1' if 'direct' in str(cfg.get('mode','')) else 'base'
 if cfg.get('original_kernel'):label+='/original-profile'
 key=(camp,fam,str(label));variants[key][c['phase']].add(c['graph']);variants[key]['configs'].add(c['variant'])
vr=[]
for (camp,fam,label),z in sorted(variants.items()):
 vr.append(dict(campaign=camp,family=fam,variant=label,profile_graphs=len(z['profile']),timing_graphs=len(z['timing']),profile_graph_list=';'.join(sorted(z['profile'])),timing_graph_list=';'.join(sorted(z['timing'])),exact_config_groups=len(z['configs'])))
with (O/'paper_variant_graphs.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(vr[0]));w.writeheader();w.writerows(vr)
lines+=['','주요 변형은 아래와 같다. **전체 주요 변형별 그래프 목록은 '+link('paper_variant_graphs.csv')+'**, 초기 최적화·fixture별 cache/engine 설정까지 분리한 실그래프 **'+str(A['measured_variant_groups'])+'개 설정 그룹 전체는 '+link('graph_coverage.csv')+'**에 있다. 작업13 L0의 profile runner와 timing용 최종 TriMA anchor는 동일 L0 대조로 묶되 원래 설정 그룹은 CSV에 남겼다.','']
# Compact identical coverage rows only for the Markdown view.
compact=defaultdict(list)
for r in vr:compact[r['campaign'],r['family'],r['profile_graphs'],r['timing_graphs']].append(r['variant'])
lines+=tab(['캠페인','계열','변형','profile 그래프','timing 그래프'],[[camp,fam,', '.join(v),np,nt] for (camp,fam,np,nt),v in sorted(compact.items())])
lines+=['','작업13은 학습 T6개와 검증 V8개+도로망3개를 합쳐17개이며, L0/L8은17개 모두 profile과 timing이 있다. L16/32/64/128은 학습6개에서만 측정했다. suite StepTC D2는 WebCC profile을 완료해 profile14/timing13이고 D3는13/13이다. multiply-shift의 weak mix0 포팅은13개, mix1/2는14개다. TriMA mix0/1/2는각14개, 작업19/20의 두 구성은각17개다. Polak은14개이며 도로망을 측정하지 않았다. 순서 의존성10부분집합은각2개(com-LJ, com-Orkut)다.','','## 재현과 검증','','집계 코드: [collect.py](final-totals-v1/collect.py) → [report.py](final-totals-v1/report.py) → [write_report.py](final-totals-v1/write_report.py). 모두 로컬 파일만 처리한다. 신규 장치/CPU oracle를 실행하지 않는다. 입력 증거 SHA 목록은 '+link('source_manifest.csv')+'다. [AUDIT.json](final-totals-v1/AUDIT.json)에 합계·중복 제거·한도·주요 캠페인 셀 수 교차 검사를 기록했다. `scope_complete=false`는 검사 실패가 아니라 위에 명시한 과거 leaf 기록 누락을 뜻한다.','','논문에는 확인된 하한과 범위 제한을 함께 인용하는 것이 안전하다. 누락한 hash-mix/WebCC source 원자료가 나중에 로컬에 들어오면 같은 기준으로 추가 집계할 수 있다. 현재 문서는 미측정값이나 계획 숫자로 빈칸을 채우지 않았다.']
(E/'FINAL_TOTALS.md').write_text('\n'.join(lines)+'\n')
(E/'FINAL_TOTALS.csv').write_bytes((O/'campaign_totals.csv').read_bytes())
print('Wrote FINAL_TOTALS.md, FINAL_TOTALS.csv; paper variants',len(vr))
