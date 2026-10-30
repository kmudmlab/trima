from pathlib import Path
import numpy as np,json,subprocess,traceback,hashlib
P=Path(__file__).resolve().parent;O=P/'cpu-new-fixtures-v2'
read=lambda p:json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def oracle(f,engines):
 a=np.frombuffer(f.read_bytes(),dtype='<u4');n,m=map(int,a[:2]);rp=list(map(int,a[2:n+3]));col=list(map(int,a[n+3:]));rows=[[0]*8 for e in range(engines)];ids=[];threshold=max(0,n-65536)
 def rng(lo,hi):
  lo=lo//16*16;hi=(hi+15)//16*16
  return ((hi-1)//4096-lo//4096+1 if hi>lo else 0),(hi-lo)*4
 for e in range(0,engines,2):
  q,b=rng(threshold,n+1);rows[e][2]+=q;rows[e][4]+=b;rows[e][6]+=1
 for u in range(n):
  r=rows[u%engines];q,b=rng(u,u+2);r[2]+=q;r[4]+=b;r[6]+=1
  source=col[rp[u]:rp[u+1]];d=len(source)
  if d<2:continue
  q,b=rng(rp[u],rp[u+1]);r[3]+=q;r[5]+=b;r[6]+=1
  for j in range(0,d-1,64):
   vs=source[j:min(j+64,d-1)];spans=[]
   for v in vs:
    if v>=threshold:break
    lo=v//16*16;hi=(v+17)//16*16
    if spans and lo<=spans[-1][1]+13*16:spans[-1][1]=max(spans[-1][1],hi)
    else:spans.append([lo,hi])
   for lo,hi in spans:q,b=rng(lo,hi);r[2]+=q;r[4]+=b
   if spans:r[6]+=1
   k=0
   while k<len(vs):
    words=0;k1=k
    while k1<len(vs):
     v=vs[k1];lo,hi=rp[v:v+2]
     if hi==lo:k1+=1;continue
     need=((hi+15)//16-lo//16)*16
     assert need<=16384
     if words+need>16384:break
     q,b=rng(lo,hi);r[3]+=q;r[5]+=b;words+=need;k1+=1
    r[6]+=1;r[7]+=1
    for v in vs[k:k1]:
     for kk,w in enumerate(col[rp[v]:rp[v+1]]):
      if w<=source[-1]:r[1]+=1;r[0]+=w in source;ids.append([u,v,kk,w])
    k=k1
 return rows,sorted(ids)
def main():
 O.mkdir();records=[];active=None
 try:
  for f in sorted((P/'fixtures').glob('*.csr')):
   for engines in [1,7,220]:
    want,ids=oracle(f,engines)
    for v in ['L5-T','L5-H']:
     active=dict(fixture=f.stem,engines=engines,variant=v);name=f'{f.stem}-e{engines}-{v}'
     r=subprocess.run([str(P/'middle-build-v1'/v),str(f),str(engines),'1','0'],capture_output=True,text=True);(O/(name+'.json')).write_text(r.stdout);(O/(name+'.log')).write_text(r.stderr)
     assert r.returncode==0,('kernel',active,r.stderr)
     got=json.loads(r.stdout);assert got['engine']==want,('count/candidate/QBW',active,got['engine'][:2],want[:2]);assert sorted(got['identity'])==ids,('identity',active)
     records.append(dict(**active,status='pass'))
   print(f.stem,len(records),flush=True)
  write(O/'COMPLETE.json',dict(status='pass',checks=len(records),records=records,CPU_B_kernel_actual=True,L6_model=True))
 except BaseException as e:
  write(O/'FAILURE.json',dict(error=repr(e),active=active,records=records,traceback=traceback.format_exc()));raise
if __name__=='__main__':main()
