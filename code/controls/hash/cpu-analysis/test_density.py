"""독립 Python 행 통계와 C++ 전수 집계를 fixture에서 비교한다."""
import array,csv,gzip,json,math,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parent; E=P.parents[2]
records=[]
with tempfile.TemporaryDirectory() as tmp:
 for name in ['clique140','long-collision-boundary','random12']:
  src=E/'cpu-validation-v2'/f'{name}.csr'
  a=array.array('I');a.frombytes(src.read_bytes());n,m=a[:2];rp=a[2:n+3];col=a[n+3:];deg=[rp[u+1]-rp[u] for u in range(n)]
  for v in col:deg[v]+=1
  out=Path(tmp)/(name+'.csv.gz');r=json.loads(subprocess.check_output(['/tmp/tritt-density',str(src),str(out)]))
  expected=[]
  for u in range(n):
   ys=col[rp[u]:rp[u+1]];d=len(ys)
   if d<=128:continue
   cons=sum(y==x+1 for x,y in zip(ys,ys[1:]));eq=sum(deg[x]==deg[y] for x,y in zip(ys,ys[1:]));same=sum(y==x+1 and deg[x]==deg[y] for x,y in zip(ys,ys[1:]))
   expected.append(dict(rank=u,forward_degree=d,undirected_degree=deg[u],tail_vertices=n-u,rho=d/(n-u),span_per_neighbor=(ys[-1]-ys[0]+1)/d,consecutive_ratio=cons/(d-1),consecutive_pairs=cons,degree_equal_pairs=eq,same_degree_consecutive_pairs=same))
  with gzip.open(out,'rt') as f:actual=list(csv.DictReader(f))
  assert len(actual)==len(expected)==r['all_degree_gt_128']['rows']
  for x,y in zip(actual,expected):
   for k,v in y.items():assert math.isclose(float(x[k]),v,rel_tol=1e-10,abs_tol=1e-10),(name,k,x[k],v)
  for k,field in [('consecutive','consecutive_pairs'),('degree_equal_pairs','degree_equal_pairs'),('same_degree_consecutive','same_degree_consecutive_pairs')]:assert r['all_degree_gt_128'][k]==sum(x[field] for x in expected)
  for key,field in [('rho_quantiles_min_p50_p90_p99_max','rho'),('span_quantiles_min_p50_p90_p99_max','span_per_neighbor'),('consecutive_quantiles_min_p50_p90_p99_max','consecutive_ratio')]:
   vs=sorted(x[field] for x in expected)
   for q,v in zip([0,.5,.9,.99,1],r[key]):assert v is None if not vs else math.isclose(v,vs[int(q*(len(vs)-1))],rel_tol=1e-10)
  records.append(dict(fixture=name,status='pass',rows=len(actual)))
print(json.dumps(dict(status='pass',records=records),indent=2))
