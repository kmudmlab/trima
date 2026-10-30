#!/usr/bin/env python3
"""로컬 CPU: 공개 SNAP 도로망을 기존 degree/ID numeric-forward CSR로 변환."""
import argparse,gzip,hashlib,json,socket,time
from pathlib import Path
import numpy as np
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--downloads',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
assert socket.gethostname() not in ['tt','dmlab-tt']
a.out.mkdir(parents=True,exist_ok=False)
expected={'PA':(1088092,1541898,67150),'TX':(1379917,1921660,82869),'CA':(1965206,2766607,120676)}
for state,(nn,mm,triangles) in expected.items():
 name='roadNet-'+state;src=a.downloads/(name+'.txt.gz');start=time.time()
 with gzip.open(src,'rt') as f:edges=np.loadtxt(f,dtype=np.uint32,comments='#')
 raw_edges=len(edges);loops=int(np.count_nonzero(edges[:,0]==edges[:,1]));assert loops==0
 edges.sort(axis=1);edges=np.unique(edges,axis=0)
 ids=np.unique(edges);n=len(ids);m=len(edges);assert (n,m)==(nn,mm),(name,n,m)
 compact=np.searchsorted(ids,edges);degree=np.bincount(compact.ravel(),minlength=n)
 order=np.lexsort((ids,degree));rank=np.empty(n,dtype=np.uint32);rank[order]=np.arange(n,dtype=np.uint32)
 remapped=rank[compact];remapped.sort(axis=1);remapped=remapped[np.lexsort((remapped[:,1],remapped[:,0]))]
 # Invert all edges and compare the exact set, not only its size/hash.
 inverse=ids[order];back=inverse[remapped];back.sort(axis=1);back=back[np.lexsort((back[:,1],back[:,0]))]
 assert np.array_equal(back,edges),'undirected edge set changed'
 counts=np.bincount(remapped[:,0],minlength=n);rp=np.concatenate(([0],np.cumsum(counts))).astype('<u4');col=remapped[:,1].astype('<u4')
 path=a.out/(name+'.csr')
 with path.open('xb') as f:
  np.array([n,m],dtype='<u4').tofile(f);rp.tofile(f);col.tofile(f)
 np.save(a.out/(name+'-rank-to-original.npy'),inverse)
 meta=dict(graph=name,n=n,m=m,count=triangles,count_status='SNAP reference; independent CPU count pending',input_sha256=sha(path),raw_sha256=sha(src),raw_directed_records=raw_edges,
  duplicates_and_reverse_records_removed=raw_edges-m,self_loops=loops,orientation='ascending (undirected degree, original SNAP ID), then dense rank',undirected_edge_set_exact=True,
  max_forward_degree=int(counts.max()),mean_forward_degree=float(counts.mean()),short_rows_lt8_fraction=float(np.mean(counts<8)),
  source_url='https://snap.stanford.edu/data/'+name+'.html',download_url='https://snap.stanford.edu/data/'+name+'.txt.gz',host=socket.gethostname(),preparation_s=time.time()-start)
 (a.out/(name+'.json')).write_text(json.dumps(meta,indent=2)+'\n');print(name,n,m,'prepared',flush=True)
