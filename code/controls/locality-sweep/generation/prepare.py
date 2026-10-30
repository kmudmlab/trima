from pathlib import Path
import numpy as np
import os,socket,json,hashlib,subprocess,traceback,importlib.util
S=Path(__file__).resolve().parent;P=S.parent;O=S/'inputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,d):p.write_text(json.dumps(d,indent=2)+'\n')
def main():
 assert 'bear' in socket.gethostname() or os.uname().sysname=='Darwin';O.mkdir(exist_ok=False);records=[]
 spec=importlib.util.spec_from_file_location('graph',P/'code/generation/repository_graph.py');graph=importlib.util.module_from_spec(spec);spec.loader.exec_module(graph)
 def orient(name,edges,n,perm=None,**extra):
  u=(edges>>32).astype(np.int64);v=(edges&0xffffffff).astype(np.int64)
  if perm is not None:u=perm[u].astype(np.int64);v=perm[v].astype(np.int64)
  deg=np.bincount(u,minlength=n)+np.bincount(v,minlength=n);order=np.lexsort((np.arange(n,dtype=np.uint32),deg));rank=np.empty(n,np.uint32);rank[order]=np.arange(n,dtype=np.uint32)
  rp,col=graph.build_csr(rank[u],rank[v],n);assert len(col)==len(edges)
  inv=order if perm is None else np.argsort(perm)[order];bu=np.repeat(inv,np.diff(rp).astype(np.int64));bv=inv[col];back=(np.minimum(bu,bv).astype(np.uint64)<<32)|np.maximum(bu,bv).astype(np.uint64);back.sort();assert np.array_equal(back,edges)
  file=O/(name+'.csr')
  with file.open('xb') as f:np.array([n,len(col)],'<u4').tofile(f);rp.astype('<u4').tofile(f);col.astype('<u4').tofile(f)
  np.save(O/(name+'-rank-to-original.npy'),inv.astype(np.uint32));d=np.diff(rp);bound=np.unique(rp[1:-1]);bound=bound[(bound>0)&(bound<len(col))];con=int(np.count_nonzero(col[1:]==col[:-1]+1))-int(np.count_nonzero(col[bound]==col[bound-1]+1));pairs=int(len(col)-np.count_nonzero(d))
  r=dict(graph=name,n=n,m=len(col),max_forward_degree=int(d.max()),input_sha256=sha(file),rank_to_original_sha256=sha(O/(name+'-rank-to-original.npy')),undirected_edge_set_exact=True,orientation='degree ascending, ties by relabeled/original ID; dense rank, repository build_csr unchanged',consecutive_pairs=con,within_row_pairs=pairs,consecutive_pair_share=con/pairs if pairs else 0,**extra)
  with (O/(name+'-oracle.json')).open('x') as out,(O/(name+'-oracle.log')).open('x') as err:subprocess.run([str(P/'build-v1/oracle'),str(file)],stdout=out,stderr=err,check=True)
  oracle=json.loads((O/(name+'-oracle.json')).read_text());r['count']=oracle['count'];r['oracle_sha256']=sha(O/(name+'-oracle.json'))
  expected=r.get('analytic_triangle_count',r.get('original_triangle_count'));assert oracle['count']==expected,('triangle mismatch',name,oracle['count'],expected)
  r['schedules']={}
  for fam,mode in [('wetric',2),('tricore',6)]:
   schedule=O/(name+'-'+fam+'-schedule.bin');cmd=[str(P/'build-v1'/(fam+'-D0')),str(file),str(schedule),str(mode),'0'];res=subprocess.run(cmd,capture_output=True,text=True);assert res.returncode==0,res.stderr
   info=json.loads(res.stdout);manifest=O/(name+'-'+fam+'-manifest.json');write(manifest,dict(input_sha256=r['input_sha256'],schedule_sha256=sha(schedule),info=info,cpu_replay_performed=False,command=cmd));r['schedules'][fam]=dict(path=schedule.name,manifest=manifest.name,sha256=sha(schedule))
  write(O/(name+'.json'),r);records.append(r);write(S/'status.json',dict(status='preparing',graphs=len(records),graph=name,pid=os.getpid()));print('PASS input+oracle',name,flush=True)
 raw=P/'inputs-v1/S2-ef4-undirected.u64';meta=json.loads((P/'inputs-v1/S2-ef4.json').read_text());assert sha(raw)==meta['raw_edges_sha256'];bfs=O/'S2-ef4-bfs-permutation.u32';subprocess.run([str(P/'code/generation/bfs'),str(raw),str(1<<20),str(bfs)],check=True);perm=np.fromfile(bfs,dtype='<u4');assert len(np.unique(perm))==1<<20
 original=json.loads((P/'cpu-v1/S2-ef4/oracle.json').read_text())['count'];orient('S2-ef4-bfs',np.memmap(raw,dtype='<u8',mode='r'),1<<20,perm,bfs_policy='ascending original-ID component roots and sorted neighbors; isolates included',original_triangle_count=original,source_edges_sha256=sha(raw),bfs_binary_sha256=sha(P/'code/generation/bfs'))
 side=1024;ids=np.arange(side*side,dtype=np.uint64).reshape(side,side);u=np.concatenate([ids[:,:-1].ravel(),ids[:-1,:].ravel(),ids[:-1,:-1].ravel()]);v=np.concatenate([ids[:,1:].ravel(),ids[1:,:].ravel(),ids[1:,1:].ravel()]);edges=(u<<32)|v;edges.sort();assert np.all(edges[1:]>edges[:-1]);assert len(edges)==3*side*side-4*side+1
 orient('grid2d-tri-1024',edges,side*side,side=side,original_ids='row major r*side+c',diagonal='NW-SE once per cell: (r,c) to (r+1,c+1)',analytic_triangle_count=2*(side-1)**2)
 write(S/'CPU_READY.json',dict(status='pass',graphs=2,device_profile_cells=8,cpu_validation='independent triangle total only; no Q/B/W replay',records=records,csr_builder_sha256=sha(P/'code/generation/repository_graph.py'),oracle_binary_sha256=sha(P/'build-v1/oracle')));write(S/'status.json',dict(status='cpu_ready',graphs=2,pid=os.getpid()))
if __name__=='__main__':
 try:main()
 except BaseException as e:write(S/'failure.json',dict(error=repr(e),traceback=traceback.format_exc()));raise
