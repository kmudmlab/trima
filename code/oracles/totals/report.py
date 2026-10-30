#!/usr/bin/env python3
"""Evidence aggregation, never invokes SSH/device/compiler or experimental runners."""
import csv,json,hashlib,datetime
from collections import Counter,defaultdict
from pathlib import Path
E=Path(__file__).resolve().parents[1];O=Path(__file__).resolve().parent;G=E/'optimization_20261022/gap';GP='optimization_20261022/gap/'
D=json.loads((O/'inventory.json').read_text());sources=set(json.loads((O/'source_paths.json').read_text()))
GRAPHS=['fb','notredame','stanford','google','berkstan','wikitalk','skitter','patents','comlj','soclj','hollywood','orkut','friendster','webcc','roadNet-PA','roadNet-TX','roadNet-CA']
def read(p):return json.loads(p.read_text())
def csvout(name,rows):
 assert rows,name
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with (O/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def evidence(p):
 p=Path(p);rel=str(p.relative_to(E));sources.add(rel);return rel
# Failed runs are classified by retained logs, never relabeled count failures.
failclasses={
'optimization_20261022/cooperative-study/fixture-clique140-slots2-kib4':('failed_host_api','io_tensors.size() >= 2 assertion before Count'),
'optimization_20261022/pilot/fixture-0-wetric-opt0':('failed_compile','-Werror=misleading-indentation'),
GP+'suite-v1/source-device-fixtures-v1/fixture-clique140-trima':('failed_host_api',"ComputeConfigDescriptor object is not subscriptable"),
GP+'suite-v1/webcc-direct-continue-v1/profile-steptc-D3-oa-w4':('interrupted_time_limit','User-authorized weak-hash D3 interruption; no completed profile')}
for key,(status,why) in failclasses.items():D[key].update(status=status,reason=why)
# Explicit planned omissions; D3 already represented as interrupted, not counted twice.
skipfile=G/'suite-v1/webcc-policy-v2/skipped-cells.json';evidence(skipfile)
for r in read(skipfile)['cells']:
 if r['phase']=='profile' and r['variant']=='D3-oa-w4':continue
 v=r['variant'];key=GP+'suite-v1/explicit-skips/'+r['phase']+'-'+str(r.get('block',''))+'-'+v
 D[key]=dict(cell_id=key,campaign='suite-v1',phase='profile' if 'profile' in r['phase'] else 'timing',status=r['status'],family='steptc' if v.startswith('D') else 'trust',graph='webcc',variant_label=v,variant='not_measured',files=[str(skipfile.relative_to(E))],records=[],runtime_cb=[],host_cb_bytes=None,runtime_cb_bytes=None,reason='weak_hash_time_budget')
for p in (G/'multiply-shift-v2').rglob('not-measured.json'):
 for r in read(p):
  evidence(p)
  for phase,block in [('profile',None),('timing',0),('timing',1),('timing',2)]:
   key=str(p.parent.relative_to(E))+'/explicit-skip-'+phase+'-'+str(block)+'-'+r['key']
   D[key]=dict(cell_id=key,campaign='multiply-shift-v2',phase=phase,status=r['status'],family=r['key'].split('-')[0],graph='webcc',variant_label=r['key'],variant='not_measured',files=[str(p.relative_to(E))],records=[],runtime_cb=[],host_cb_bytes=None,runtime_cb_bytes=None,reason='weak_hash_time_budget')
# Other failures happened before a device cell, so report a separate unit.
incidents=[dict(campaign='task13',unit='prelaunch_cell',count=1,classification='runner_input_mapping',source=GP+'recovery-20261024-evening-v1/task13.log',detail='validation-roadNet-PA-profile-L0 Popen argument None; recovered in roads-recovery-v1'),dict(campaign='multiply-shift-v1',unit='campaign_stage',count=1,classification='runner_path_expression',source=GP+'multiply-shift-v1/trima/fb.log',detail='str / str in trima-fb setup; no started child cell'),dict(campaign='trisc',unit='campaign_stage',count=1,classification='missing_manifest',source=GP+'trisc-v1/stanford-v1/setup-failure.log',detail='preflight.json missing before cell creation'),dict(campaign='locality',unit='cpu_preparation_stage',count=1,classification='missing_candidate_diagnostic',source=GP+'locality-v1/device-prepared-v1/failure.json',detail='No device invocation; replacement v2 preserved'),dict(campaign='aux-rowptr-device',unit='profile_io_metadata',count=34,classification='counter_publication_or_aggregation',source=GP+'aux-rowptr-device-v1/campaign-v1/CPU_DEVICE_COMPARISON.csv',detail='34 IO comparisons false; all triangle/candidate counts true; corrected 34/34 in aux-rowptr-profile-v2')]
# CPU case counts: independent execution reports; reports/mirror copies are not counted twice.
cpu=[]
def addcpu(p,camp,field,note='',category='semantic',n=None,partial=False):
 d=read(p);value=d[field] if n is None else n
 assert isinstance(value,int) and value>=0
 assert d.get('status')=='pass' or partial
 cpu.append(dict(campaign=camp,report=evidence(p),field=field,category=category,passed_checks=value,report_status=d.get('status'),partial=partial,note=note,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
for p in sorted(E.rglob('verification.json')):
 if 'final-totals-v1' in p.parts:continue
 rel=str(p.relative_to(E));camp='initial-port' if rel.startswith('cpu-validation') else 'optimization'
 addcpu(p,camp,'checks','개별 실행 보고서; opt0/1/2는 출력 정답이 같아도 서로 다른 설정의 검사')
addcpu(G/'trisc-v1/cpu-v1/summary.json','trisc','semantic_cells')
addcpu(G/'trisc-v1/cpu-v1/summary.json','trisc','schedules',category='supporting')
for sub,camp in [('hash-mix','hash-mix'),('multiply-shift','multiply-shift-v1')]:
 for k in ('steptc_checks','source_semantic_checks'):addcpu(G/sub/'cpu-v1/summary.json',camp,k)
for k,cat in [('fixture_engine_checks','semantic'),('stage_alignment_size_cases','supporting')]:addcpu(G/'aux-rowptr-device/fixture-prepared/summary.json','aux-rowptr-device',k,category=cat)
for k,cat,camp in [('combined_fixture_engine_checks','semantic','trima-final'),('slot_mask_checks','supporting','trima-final'),('publish_zero_poison_carry_checks','supporting','aux-rowptr-counterfix')]:addcpu(G/'aux-rowptr-followup/cpu-v1/summary.json',camp,k,category=cat)
for sub in ['trima-supply-v1','trima-supply-final']:addcpu(G/sub/'cpu-v1/summary.json','task13','checks','서로 다른 cpu_supply.cpp SHA의 두 구현 세대')
for name in ['LAYOUT_TESTS.json','COUNTER_LAYOUT_TESTS.json']:addcpu(G/'trima-supply-final'/name,'task13','checks',category='supporting')
for k in ('base_direct_checks','upstream_trace_checks'):addcpu(G/'polak-v1/cpu-v1/summary.json','polak',k)
for sub in ['cpu-ports-v1','cpu-ports-v2','cpu-ports-v3']:
 p=G/'polak-v1'/sub/'summary.json';d=read(p);addcpu(p,'polak','checks','실패 보고서의 checks는 실패 전 완료분' if d['status']=='failed' else '',partial=d['status']=='failed')
 if d['status']=='failed':incidents.append(dict(campaign='polak',unit='cpu_check_stage',count=1,classification='cpu_harness_or_input_contract',source=evidence(p),detail=d['error']))
addcpu(G/'polak-priority/prepared-v3/summary.json','polak','checks',category='preparation')
addcpu(G/'locality-v1/device-prepared-v2/summary.json','locality','checks',category='preparation')
# Request replay and preparation checks have distinct units, never counted as triangle-oracle semantics.
addcpu(G/'locality-v1/fixture-replay-v1/summary.json','locality','exact',category='io_replay')
addcpu(G/'locality-v1/device-prepared-v2/cross-validation.json','locality','pairs',category='io_replay')
# Exact input / candidate preflights reused by new campaigns do not create new CPU oracle tests.
csvout('cpu_checks.csv',cpu)
# Cell ledger, no performance values are copied.
ledger=[]
for k,c in sorted(D.items()):
 provenance=sorted(set(c['files']+[r['_source'] for r in c['records']]))
 ledger.append(dict(cell_id=k,campaign=c['campaign'],family=c['family'],variant_label=c.get('variant_label',''),variant_config=c['variant'],graph=c['graph'],phase=c['phase'],status=c['status'],host_cb_KiB=c['host_cb_bytes']/1024 if c['host_cb_bytes'] is not None else '',runtime_cb_KiB=c['runtime_cb_bytes']/1024 if c['runtime_cb_bytes'] is not None else '',runtime_cb_records=len(c['runtime_cb']),reason=c.get('reason',''),sources=';'.join(provenance)))
csvout('cells.csv',ledger)
csvout('incidents.csv',incidents)
failed=[r for r in ledger if r['status']!='pass'];csvout('failed_and_unmeasured.csv',failed)
# Runtime readbacks are physical observations; host declared L1 sizes remain a separate evidence class.
cbrows=[]
for c in D.values():
 for a in c['runtime_cb']:
  assert a['addresses'] and a['bytes']==a['descriptor_sum'],a
  cbrows.append(dict(cell_id=c['cell_id'],campaign=c['campaign'],family=c['family'],variant_label=c.get('variant_label'),record=a['path'],cb_KiB_per_core=a['bytes']/1024,limit_KiB=1392,over_limit=a['bytes']>1392*1024,address_readback=True,observed_cores=a['core_count']))
csvout('cb_runtime_records.csv',cbrows)
# Exact config groups provide graph coverage and the full runtime-missing variant list.
groups=defaultdict(list)
for c in D.values():
 if c['status']=='pass':groups[c['campaign'],c['family'],c['variant']].append(c)
coverage=[];missing=[];cbvariant=[]
for (camp,fam,variant),cs in sorted(groups.items()):
 vid=hashlib.sha256((camp+'|'+fam+'|'+variant).encode()).hexdigest()[:12]
 real=[c for c in cs if c['phase'] in ('profile','timing') and c['graph'] in GRAPHS]
 prof={c['graph'] for c in real if c['phase']=='profile'};tim={c['graph'] for c in real if c['phase']=='timing'}
 labels=sorted({c.get('variant_label','') for c in cs})
 item=dict(campaign=camp,family=fam,variant_id=vid,labels=';'.join(labels),variant_config=variant,profile_graphs=len(prof),timing_graphs=len(tim),any_measured_graphs=len(prof|tim),suite_graphs=len((prof|tim)&set(GRAPHS[:14])),road_graphs=len((prof|tim)&set(GRAPHS[14:])),profile_graph_list=';'.join(g for g in GRAPHS if g in prof),timing_graph_list=';'.join(g for g in GRAPHS if g in tim),measured_cells=len(real))
 if real:coverage.append(item)
 rt=[c['runtime_cb_bytes'] for c in cs if c['runtime_cb_bytes'] is not None];host=[c['host_cb_bytes'] for c in cs if c['host_cb_bytes'] is not None]
 row={k:item[k] for k in ('campaign','family','variant_id','labels','variant_config')};row.update(passed_cells=len(cs),runtime_observed_cells=sum(c['runtime_cb_bytes'] is not None for c in cs),host_only_cells=sum(c['runtime_cb_bytes'] is None and c['host_cb_bytes'] is not None for c in cs),allocation_unknown_cells=sum(c['runtime_cb_bytes'] is None and c['host_cb_bytes'] is None for c in cs),max_runtime_cb_KiB=max(rt)/1024 if rt else '',max_host_declared_cb_KiB=max(host)/1024 if host else '',runtime_over_limit=any(x>1392*1024 for x in rt),host_over_limit=any(x>1392*1024 for x in host))
 cbvariant.append(row)
 if not rt:missing.append(dict(row,evidence_class='host_declared_only' if host else 'no_numeric_allocation_record'))
csvout('graph_coverage.csv',coverage);csvout('cb_variants.csv',cbvariant);csvout('cb_no_runtime_record.csv',missing)
# Family-level coverage is a union, never the sum of variant graph counts.
familyrows=[]
for fam in sorted({c['family'] for c in D.values()}):
 cs=[c for c in D.values() if c['status']=='pass' and c['family']==fam and c['phase'] in ('profile','timing')];gs={c['graph'] for c in cs}&set(GRAPHS)
 if gs:familyrows.append(dict(family=fam,graphs=len(gs),suite_graphs=len(gs&set(GRAPHS[:14])),road_graphs=len(gs&set(GRAPHS[14:])),graphs_list=';'.join(g for g in GRAPHS if g in gs)))
csvout('family_graphs.csv',familyrows)
# Campaign summaries are disjoint physical attempts; reruns in different output dirs remain separate.
camps=sorted({c['campaign'] for c in D.values()}|{c['campaign'] for c in cpu})
summary=[]
for camp in camps:
 cs=[c for c in D.values() if c['campaign']==camp];us=[x for x in cpu if x['campaign']==camp];passed=[c for c in cs if c['status']=='pass']
 row=dict(campaign=camp,cpu_oracle_semantic_pass=sum(x['passed_checks'] for x in us if x['category']=='semantic'),cpu_supporting_pass=sum(x['passed_checks'] for x in us if x['category']=='supporting'),cpu_preparation_pass=sum(x['passed_checks'] for x in us if x['category']=='preparation'),cpu_io_replay_pass=sum(x['passed_checks'] for x in us if x['category']=='io_replay'),fixture_pass=sum(c['phase']=='fixture' for c in passed),profile_pass=sum(c['phase']=='profile' for c in passed),timing_pass=sum(c['phase']=='timing' for c in passed),host_fastpath_pass=sum(c['phase']=='host_fastpath' for c in passed),failed_cells=sum(c['status'].startswith('failed') for c in cs),interrupted_cells=sum(c['status'].startswith('interrupted') for c in cs),unmeasured_cells=sum(c['status'].startswith('not_measured') for c in cs),prelaunch_cell_failures=sum(x['count'] for x in incidents if x['campaign']==camp and x['unit']=='prelaunch_cell'),setup_stage_failures=sum(x['count'] for x in incidents if x['campaign']==camp and x['unit']=='campaign_stage'),cpu_stage_failures=sum(x['count'] for x in incidents if x['campaign']==camp and x['unit'] in ('cpu_check_stage','cpu_preparation_stage')),io_counter_issue_cells=sum(x['count'] for x in incidents if x['campaign']==camp and x['unit']=='profile_io_metadata'))
 summary.append(row)
totals={k:sum(r[k] for r in summary) for k in summary[0] if k!='campaign'}
csvout('campaign_totals.csv',summary+[dict(campaign='TOTAL_LOCAL_VERIFIED',**totals)])
# Explicitly enumerate missing result collections, do not turn plans into successes.
gaps=[dict(campaign='hash-mix',record_kind='parent_stage_success_only',source=GP+'recovery-20261024-evening-v1/old-failure-evidence/status.json',detail='ports-14 graphs all rc0; referenced leaf port campaign dirs absent locally; historical plan596 is not a verified leaf count',planned_cells=596,verified_cells='',action='Remote access prohibited; report only'),dict(campaign='suite-v1',record_kind='parent_stage_success_only',source=GP+'recovery-20261024-evening-v1/old-failure-evidence/status.json',detail='webcc-pending-source-baselines rc0; suite WebCC source leaf records absent locally',planned_cells='',verified_cells='',action='Remote access prohibited; no imputation'),dict(campaign='hash-mix',record_kind='superseded_plan',source=GP+'HASH_MIX_RESULTS.md',detail='Old 52 fixture/708 real plan and waiting status are stale; later campaigns replace parts; never count the plan as measured',planned_cells='',verified_cells='',action='Retain history')]
csvout('evidence_gaps.csv',gaps)
# Static preflight-only rows are an independent list; graph/family/variant planned values, not runtime claims.
pre=read(G/'suite-v1/preflight.json');static=[]
for g in pre['graphs']:
 for v in g['variants']:
  static.append(dict(graph=g['graph'],family=v.get('family'),variant=v.get('variant'),static_l1_KiB=v.get('l1_bytes',0)/1024,static_capacity_pass=v.get('static_capacity_pass'),runtime_allocation_verified_in_preflight=v.get('runtime_allocation_verified'),source=GP+'suite-v1/preflight.json'))
csvout('static_preflight_inventory.csv',static)
# Validate sums, uniqueness, and known independently reported completed campaign sizes.
assert len(ledger)==len({r['cell_id'] for r in ledger})
for camp,want in [('trisc',125),('polak',120),('locality',90),('aux-rowptr-device',148),('aux-rowptr-counterfix',40),('trima-final',148),('task13',256),('order-dependence-final',80),('multiply-shift-v2',988)]:
 got=sum(c['status']=='pass' for c in D.values() if c['campaign']==camp);assert got==want,(camp,got,want)
assert all(c['graph'] in GRAPHS for c in D.values() if c['status']=='pass' and c['phase'] in ('profile','timing'))
assert not any(c.get('conflict') for c in D.values())
# Content provenance for canonical input reports (not binaries or tensor raw arrays).
for x in incidents+gaps:sources.add(x['source'])
manifest=[]
for r in sorted(sources):
 p=E/r
 if p.is_file():manifest.append(dict(path=r,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size))
csvout('source_manifest.csv',manifest)
proof=dict(status='pass',local_only=True,unique_cell_records=len(ledger),campaign_rows=len(summary),totals=totals,runtime_cb_cells=len({r['cell_id'] for r in cbrows}),runtime_cb_records=len(cbrows),max_runtime_cb_KiB=max(r['cb_KiB_per_core'] for r in cbrows),runtime_cb_over_limit=sum(r['over_limit'] for r in cbrows),max_host_declared_cb_KiB=max(c['host_cb_bytes'] for c in D.values() if c['host_cb_bytes'] is not None)/1024,measured_variant_groups=len(coverage),variants_without_runtime_cb=len(missing),scope_complete=False,scope_limitation='historical hash-mix and WebCC source leaves missing locally')
(O/'AUDIT.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,ensure_ascii=False,indent=2))
