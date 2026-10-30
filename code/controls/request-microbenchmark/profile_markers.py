"""기존 profile만 읽는다. timing 정보는 사용하지 않는다."""
import argparse,csv,hashlib,json
from pathlib import Path
P=Path(__file__).resolve().parent;G=P.parent
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False);rows=[]
for p in sorted((G/'suite-v1').glob('*/profile-*/profile.json')):
 d=json.loads(p.read_text())
 if d.get('family') not in ['steptc','wetric','tricore'] or d.get('variant') not in ['base','D1-direct']:continue
 if d['graph']=='webcc' and 'continue-v2' not in str(p):continue
 c=d['counters'];rq=c['range_requests_row_col_aux'];rb=c['range_bytes_row_col_aux'];base=sum(c[k] for k in ['row_pages','col_pages','aux_pages'])
 rows.append(dict(graph=d['graph'],family=d['family'],variant=d['variant'],page_bytes=d['page_bytes'],range_requests=sum(rq),range_bytes=sum(rb),mean_range_bytes=sum(rb)/sum(rq) if sum(rq) else None,
  **{f'mean_range_{name}_bytes':b/q if q else None for name,q,b in zip(['row','col','aux'],rq,rb)},residual_page_requests=base,page_request_bytes=d['page_bytes'],profile_path=str(p.relative_to(G)),profile_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),input_sha256=d['input_sha256']))
assert rows
with (a.out/'port-profile-markers.csv').open('x') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
(a.out/'summary.json').write_text(json.dumps(dict(status='pass',profile_cells=len(rows),graphs=sorted({r['graph'] for r in rows}),device_microbenchmark_cells=0,definition='D1 sum(range bytes)/sum(range requests); residual page misses separate'),indent=2)+'\n')
print(len(rows),'existing profile cells; no timing read')
