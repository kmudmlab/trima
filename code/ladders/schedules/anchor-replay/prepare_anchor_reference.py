"""Reuse byte-identified CPU traces for unchanged port anchors; preserve settings."""
import hashlib,json
from pathlib import Path
P=Path(__file__).resolve().parent;G=P.parent
read=lambda p:json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 out=P/'anchor-replay';out.mkdir(exist_ok=False);records=[]
 anchors=read(G/'task22/ANCHORS_FROZEN.json')['anchors']+read(G/'task22-large/ANCHORS_FROZEN.json')['anchors']
 for a in anchors:
  if a['graph']=='webcc' or a['anchor_kind']!='port':continue
  o=a['options'];g=a['graph'];family=a['family'];direct='direct' in o['mode'];pb=1024 if family=='steptc' else 256
  assert o['page_bytes']==pb and [o[k] for k in ['row_cache_kib','col_cache_kib','aux_cache_kib']]==[16,64,16]
  assert o['opt_level']==(3 if family=='tricore' else 2)
  assert o['meta_stage']==64 and o['arena_kib']==64 and o['spread']==127 and o['tail']==0
  assert [o[k] for k in ['tc_chunk','tc_held','tc_bound']]==[32,1,1]
  src=G/'bundle-replay-v1/graphs'/f'{g}-{family}-'+Path('unused') if False else G/'bundle-replay-v1/graphs'/f'{g}-{family}-{"D1-direct" if direct else "base"}'
  cpu=read(src/'stdout.json');comparison=read(src/'comparison.json')
  assert comparison['status']=='exact' and comparison['delta']==[0]*12
  assert len(cpu['engine_io'])==220
  rows=[]
  for e,io in enumerate(cpu['engine_io']):
   q=[io[k]+io[k+3] for k in range(3)];b=[io[k]*pb+io[k+6] for k in range(3)]
   rows.append([cpu['engine_counts'][e],cpu['engine_candidates'][e],None,None,*q,*b,io[9]])
  result=dict(engines=rows,fields=['count','candidates','identity1','identity2','rowQ','colQ','scheduleQ','rowB','colB','scheduleB','W'],
              source=str(src.relative_to(G)),cpu_sha256=sha(src/'stdout.json'),comparison_sha256=sha(src/'comparison.json'),input_sha256=comparison['input_sha256'],anchor=a,
              reuse_reason='Unchanged cache/range traversal and ownership. Frozen hash/probe grouping changes run on resident rows and issue no additional IO. No endpoint pair array.')
  dst=out/f'{family}-{g}.json';dst.write_text(json.dumps(result,indent=2)+'\n');records.append(dict(family=family,graph=g,status='verified_cpu_trace_reused',file=dst.name))
 assert len(records)==44
 (out/'PORT_COMPLETE.json').write_text(json.dumps(dict(status='pass',anchors=44,records=records,new_cpu_traversal=False),indent=2)+'\n')
if __name__=='__main__':main()
