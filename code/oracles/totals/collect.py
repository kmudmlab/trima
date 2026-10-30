#!/usr/bin/env python3
"""Local evidence only. No network, subprocess, device, or measurement calls."""
from pathlib import Path
from collections import defaultdict,Counter
import json,re,csv,hashlib
E=Path(__file__).resolve().parents[1];O=Path(__file__).resolve().parent;G=E/'optimization_20261022/gap';OPT='optimization_20261022/';GP=OPT+'gap/'
ROOTS=[E/'results/tt',E/'optimization_20261022/results']+[G/n for n in ('bottomup-v1','topdown-v1','coop-v1','direct-v1','smoke-direct','smoke-fb','nocounters-v1','trisc-v1','suite-v1','hash-mix/campaign-v1','hash-mix/ports-v1','multiply-shift-v1','multiply-shift-v2','aux-rowptr-device-v1/campaign-v1','aux-rowptr-profile-v2','trima-final-v1','trima-supply-v1/campaign-recovery-v1','trima-supply-v1/roads-recovery-v1','polak-v1/profile-priority-v1','polak-v1/timing-priority-v1','locality-v1/device-v1','order-dependence-v1','order-dependence-original-v2')]
GRAPHS=['fb','notredame','stanford','google','berkstan','wikitalk','skitter','patents','comlj','soclj','hollywood','orkut','friendster','webcc','roadNet-PA','roadNet-TX','roadNet-CA']
cells={};aliases={};sources=set();duplicates=[]
def read(p):
 try:return json.loads(p.read_text())
 except (ValueError,OSError):return None
def rel(p):return str(p.relative_to(E))
def norm(x):
 x=str(x)
 if 'gpu_tt_portability_20261021/' in x:x=x.split('gpu_tt_portability_20261021/',1)[1]
 if x.startswith('results/tt/'):x=x[len('results/tt/'):]
 if x.startswith(OPT+'results/'):x=OPT+x[len(OPT+'results/'):]
 if x.startswith(('trisc-v1/','suite-v1/')):x=GP+x
 return x.strip('/')
def commandopts(cmd):
 d={};i=0
 while i<len(cmd):
  k=cmd[i]
  if isinstance(k,str) and k.startswith('--'):
   d[k[2:].replace('-','_')]=cmd[i+1] if i+1<len(cmd) and not str(cmd[i+1]).startswith('--') else True
  i+=1
 return d
def campaign(key):
 if not key.startswith(OPT):return 'initial-port'
 if not key.startswith(GP):return 'optimization'
 q=key[len(GP):].split('/')[0]
 return {'bottomup-v1':'gap-bottomup','topdown-v1':'gap-topdown','coop-v1':'gap-coop','direct-v1':'gap-direct','smoke-direct':'gap-direct','smoke-fb':'gap-smoke','nocounters-v1':'gap-nocounters','trisc-v1':'trisc','suite-v1':'suite-v1','multiply-shift-v1':'multiply-shift-v1','multiply-shift-v2':'multiply-shift-v2','aux-rowptr-device-v1':'aux-rowptr-device','aux-rowptr-profile-v2':'aux-rowptr-counterfix','trima-final-v1':'trima-final','trima-supply-v1':'task13','polak-v1':'polak','locality-v1':'locality','order-dependence-v1':'order-dependence-superseded','order-dependence-original-v2':'order-dependence-final','hash-mix':'hash-mix'}.get(q,q)
def cell(key):
 key=norm(key)
 if key not in cells:cells[key]=dict(cell_id=key,campaign=campaign(key),records=[],files=[],config={},summary={},events=[],declared_cb=[],runtime_cb=[])
 return cells[key]
def logevents(p):
 out=[]
 try:
  for line in p.read_text(errors='replace').splitlines():
   if line.startswith('{'):
    try:
     d=json.loads(line)
     if isinstance(d,dict):out.append(d)
    except ValueError:pass
 except OSError:pass
 return out
# Discover output dirs with actual cell summary/config/journal first; ignore analysis/CPU summaries.
for root in ROOTS:
 if not root.exists():continue
 dirs=set(p.parent for name in ('summary.json','samples.jsonl','config.json','run.jsonl','log.jsonl') for p in root.rglob(name))
 for d in sorted(dirs):
  if any(x.startswith(('cpu','analysis','source-statistics','profile-statistics')) for x in d.relative_to(root).parts):continue
  summ=read(d/'summary.json') or {};cfg=read(d/'config.json') or {};events=[]
  for name in ('samples.jsonl','run.jsonl','log.jsonl'):events+=logevents(d/name)
  cfg=next((x for x in events if x.get('kind')=='config'),cfg)
  if not (cfg.get('input') or summ.get('median_s') is not None or any(x.get('kind')=='complete' and ('median_s' in x or 'samples' in x) for x in events)):continue
  key=norm(cfg.get('out',rel(d)));aliases[rel(d)]=key;c=cell(key);c['files'].append(rel(d));c['config'].update(cfg);c['summary'].update(summ);c['events']+=events
  for p in (d/'summary.json',d/'config.json',d/'samples.jsonl'):
   if p.exists():sources.add(rel(p))
# Leaf status records with --out are process attempts; orchestration stage records are excluded.
for root in ROOTS:
 if not root.exists():continue
 for p in root.rglob('status.json'):
  if any(x.startswith(('cpu','analysis','source-statistics','local-mirror')) for x in p.relative_to(root).parts):continue
  d=read(p)
  if not isinstance(d,dict):continue
  for field in ('records','fixtures'):
   records=d.get(field,[])
   if not isinstance(records,list):continue
   for r in records:
    if not isinstance(r,dict):continue
    cmd=r.get('command',[]);opts=commandopts(cmd)
    if 'out' not in opts:continue
    key=norm(opts['out']);c=cell(key);c['records'].append(dict(r,_source=rel(p)));c['config'].update({k:v for k,v in opts.items() if k not in c['config']});sources.add(rel(p))
    if not c['files']:
     name=r.get('name') or Path(key).name;possible=p.parent/name
     if possible.exists():c['files'].append(rel(possible))
    if 'result' in r and isinstance(r['result'],dict):c['summary'].update(r['result'])
    if 'summary' in r and isinstance(r['summary'],dict):c['summary'].update(r['summary'])
# Merge output aliases discovered from status where raw journal lacked out.
for key,c in list(cells.items()):
 for loc in c['files']:
  alt=norm(loc)
  if alt!=key and alt in cells:
   a=cells.pop(alt)
   for k in ('records','files','events'):c[k]+=a[k]
   for k in ('config','summary'):c[k]={**a[k],**c[k]}
   duplicates.append(dict(alias=alt,canonical=key))
# Exclude orchestration records whose --out is a campaign directory, not a cell.
parent_keys=[k for k in cells if any(z.startswith(k+'/') for z in cells if z!=k)]
(O/'excluded_parent_records.json').write_text(json.dumps([cells.pop(k) for k in parent_keys],indent=2)+'\n')
# Complete profiles may store no summary (TriMA); successful runner returncode is authoritative.
for key,c in cells.items():
 cfg=c['config'];records=c['records'];summ=c['summary'];events=c['events']
 r=records[-1] if records else {};cmd=r.get('command',[])
 c['name']=r.get('name',Path(key).name)
 graph=r.get('graph') or (Path(str(cfg.get('input',''))).stem if cfg.get('input') else '')
 if graph not in GRAPHS:
  found=[g for g in GRAPHS if re.search(r'(^|[/_-])'+re.escape(g)+r'([/_-]|$)',key)]
  if found:graph=max(found,key=len)
 c['graph']=graph
 isfixture=('cpu-validation' in str(cfg.get('input','')) or 'fixture' in key or '/smoke/' in key or graph not in GRAPHS and bool(re.search(r'(clique|random|empty|single|collision|boundary)',key)))
 phase=r.get('phase','')
 isprofile=('profile' in phase or r.get('profile') is True or str(cfg.get('profile','')).lower()=='true' or str(cfg.get('counters',cfg.get('profile_io','0')))=='1' or 'profile-' in c['name'])
 if graph=='index-row-over-8192':isfixture=True
 if summ.get('empty_fast_path'):isfixture=True
 c['phase']='host_fastpath' if summ.get('empty_fast_path') else 'fixture' if isfixture else 'profile' if isprofile else 'timing' if graph in GRAPHS else 'unclassified'
 statuses=[x.get('status') for x in records];rcs=[x.get('returncode') for x in records if 'returncode' in x]
 success=any(x==0 for x in rcs) or summ.get('status') in ('pass','complete') or any(x.get('kind')=='complete' for x in events) or 'pass' in statuses
 fail=any(isinstance(x,int) and x!=0 for x in rcs) or summ.get('status')=='failed' or 'failed' in statuses
 skip=next((x for x in statuses if isinstance(x,str) and (x.startswith('not_') or x.startswith('skip'))),None)
 c['status']='pass' if success else skip or ('failed' if fail else 'incomplete_record')
 c['conflict']=bool(success and fail)
 family=r.get('family',r.get('mode',r.get('method',cfg.get('mode',summ.get('mode','')))))
 if not family:
  search=' '.join([str(cmd[1]) if len(cmd)>1 else '',key])
  for f in ('trima','notrisc','polak','steptc','wetric','tricore','trust','btc'):
   if f in search.lower():family=f;break
 if family=='notrisc':family='trima'
 if 'order-dependence' in key or 'bottomup-v1' in key:family='trust'
 if '/trisc-v1/' in key:family='steptc'
 c['implementation']=str(family)
 c['family']=next((f for f in ['steptc','wetric','tricore','trust','trima','polak','btc','tot'] if str(family).startswith(f)),str(family)) or 'unknown'
 label=r.get('key',r.get('variant',r.get('subset',cfg.get('cell',''))))
 if label in (None,''):label=r.get('label',r.get('level',''))
 if label in (None,''):label=c['name']
 # Exact configuration variant, excluding run/graph/profile transport options.
 option_keys=['mode','opt_level','prune','hash_oa','hash_mix','direct','lookup_width','page_bytes','row_cache_kib','col_cache_kib','aux_cache_kib','bucket_cap','hash_size','arena_kib','batch','group','contexts','aux_rowptr','no_trisc','original_kernel','short_row_threshold','short_row_cache_kib','supply_threshold','supply_cache_kib','cell','pool_banks','forward_suffix','bound_target','hybrid_factor','target_kib','slots','serial_degree','btc_adaptive','btc_maskonly','spread','tail','engines','cores','branchless','tc_bound','tc_chunk','tc_held','meta_stage','depth','logical_block','physical_tile','cooperative_batches','dm_assist','duplicate_arenas','serialize_sources','right_tiles','mask_small_rows','skip_last_row','compact_meta','max_sources_per_batch','lower_bound','prefetch','probe_limit','probe_policy','reverse_lookup','span_reads','target_cap','supply_page_bytes']
 variant={k:str(cfg[k]) for k in option_keys if k in cfg}
 # hash mix implicit original is weak; do not invent all other omitted defaults.
 c['variant']=json.dumps(variant,sort_keys=True,separators=(',',':'));c['variant_label']=str(label)
 if c['campaign']=='task13':c['variant_label']='L'+str(r.get('L',cfg.get('short_row_threshold','?')))
 for v in [cfg.get('l1_bytes'),cfg.get('l1_design_bytes'),summ.get('l1_bytes'),r.get('l1_bytes')]:
  if isinstance(v,(float,int)):c['declared_cb'].append(int(v))
 for loc in set(c['files']):
  d=E/loc
  for p in d.glob('cb-allocation*.json'):
   a=read(p)
   if not a:continue
   if 'total_cb_bytes' in a:c['runtime_cb'].append(dict(path=rel(p),bytes=a['total_cb_bytes'],addresses=bool(a.get('cb_addresses')),descriptor_sum=sum(a.get('descriptor_bytes',[])),core_count=len(a.get('cb_addresses',[]))));sources.add(rel(p))
 for ev in events:
  if ev.get('event')=='cb_discovery':
   c['runtime_cb'].append(dict(path=(c['files'][0]+'/samples.jsonl') if c['files'] else key,bytes=ev['total_bytes'],addresses=bool(ev.get('observed')),descriptor_sum=sum(ev['per_channel_bytes']),core_count=None))
 c['host_cb_bytes']=max(c['declared_cb'],default=None)
 c['runtime_cb_bytes']=max((a['bytes'] for a in c['runtime_cb']),default=None)
 if len(records)>1:duplicates.append(dict(alias=';'.join(x['_source'] for x in records),canonical=key))
# Save intermediate structured audit for deterministic iteration.
compact={}
for k,c in cells.items():
 a=dict(c)
 a['event_counts']=dict(Counter(str(e.get('kind',e.get('event','unknown'))) for e in a.pop('events')))
 a['summary']={f:v for f,v in c['summary'].items() if f in ('status','mode','count','l1_bytes','empty_fast_path')}
 a['records']=[{f:v for f,v in r.items() if f in ('_source','command','name','phase','status','returncode','profile','variant','graph','L','subset')} for r in c['records']]
 a['config']={f:v for f,v in c['config'].items() if f not in ('info','engine_results')}
 compact[k]=a
(O/'inventory.json').write_text(json.dumps(compact,indent=2)+'\n')
(O/'aliases.json').write_text(json.dumps(duplicates,indent=2)+'\n')
(O/'source_paths.json').write_text(json.dumps(sorted(sources),indent=2)+'\n')
print('cells',len(cells),'status',Counter(x['status'] for x in cells.values()),'phase',Counter(x['phase'] for x in cells.values()))
for camp in sorted({x['campaign'] for x in cells.values()}):
 sub=[x for x in cells.values() if x['campaign']==camp];print(camp,len(sub),dict(Counter((x['status'],x['phase']) for x in sub)))
print('UNCLASSIFIED',[(x['cell_id'],x['graph']) for x in cells.values() if x['phase']=='unclassified'][:30])
print('UNKNOWNFAMILY',[x['cell_id'] for x in cells.values() if x['family']=='unknown'][:30])
print('FAIL',[x['cell_id'] for x in cells.values() if x['status']!='pass'][:50])
