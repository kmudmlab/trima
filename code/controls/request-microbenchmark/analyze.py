"""Mac/bear CPU 분석: 식별성·선형 모델 적합·실측 CSV. 미완료 grid는 적합하지 않음."""
import argparse,csv,json,statistics
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent;G=P.parent;E=G.parents[1]
def fit(rows,key):
 X=np.array([[1,r['requests'],r['bytes'],r['barriers']] for r in rows],float);y=np.array([r[key] for r in rows],float)
 scale=np.maximum(np.max(abs(X),axis=0),1);Xs=X/scale
 coef,_,rank,_=np.linalg.lstsq(Xs,y,rcond=None);coef=coef/scale;pred=X@coef
 sse=float(np.sum((pred-y)**2));sst=float(np.sum((y-y.mean())**2));r2=1-sse/sst if sst else None
 d,alpha,beta,gamma=map(float,coef);valid=rank==4 and alpha>0 and beta>0 and r2 is not None and r2>=.8
 return dict(delta=d,alpha=alpha,beta=beta,gamma=gamma,r2=r2,rmse=float(np.sqrt(sse/len(y))),rank=int(rank),scaled_condition_number=float(np.linalg.cond(Xs)),crossover_bytes=alpha/beta if valid else None,alpha_10x_dominance_max_bytes=alpha/(10*beta) if valid else None,alpha_2x_dominance_max_bytes=alpha/(2*beta) if valid else None,interpretation='effective_model' if valid else 'no_positive_reliable_crossover_claim')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--campaign',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 state=json.loads((a.campaign/'status.json').read_text());rows=[];rates=[];cal=[]
 for block in range(3):
  p=a.campaign/f'calibration-{block}/summary.json'
  if not p.exists():continue
  d=json.loads(p.read_text());x=np.array([v['dm_max_ticks'] for v in d['levels'].values()]);y=np.array([v['host_seconds'] for v in d['levels'].values()]);coef=np.polyfit(x,y,1);pred=np.polyval(coef,x);r2=1-np.sum((pred-y)**2)/np.sum((y-y.mean())**2)
  cal.append(dict(block=block,tick_seconds=float(coef[0]),host_intercept_s=float(coef[1]),r2=float(r2),pass_local=bool(coef[0]>0 and r2>=.99)))
 valid=len(cal)==3 and all(c['pass_local'] for c in cal) and max(c['tick_seconds'] for c in cal)/min(c['tick_seconds'] for c in cal)<=1.05
 tick_seconds={c['block']:c['tick_seconds'] for c in cal} if valid else {}
 (a.out/'calibration.json').write_text(json.dumps(dict(valid_seconds_conversion=valid,blocks=cal),indent=2)+'\n')
 for rec in state['records']:
  if rec.get('kind')!='timing' or rec.get('status')!='pass':continue
  d=json.loads((a.campaign/rec['name']/'summary.json').read_text());c=d['config'];engines=c['cores']*c['engines']
  for ns,v in d['levels'].items():
   n=int(ns);q=engines*n;vol=q*c['size'];ticks=v['dm_max_ticks'];seconds=ticks*tick_seconds[rec['block']] if valid else None
   rows.append(dict(block=rec['block'],regime=f"c{c['cores']}-e{c['engines']}-{c['pattern']}",size=c['size'],batch=c['batch'],n_per_dm=n,requests=q,bytes=vol,barriers=q//c['batch'],dm_max_ticks=ticks,dm_max_seconds=seconds,host_seconds=v['host_seconds'],ticks_per_request=ticks/q if q else None,seconds_per_request=seconds/q if q and valid else None,seconds_per_byte=seconds/vol if vol and valid else None,dm_bytes_per_second=vol/seconds if seconds else None,host_bytes_per_second=vol/v['host_seconds'] if q else None))
 def csvwrite(name,data,fields=None):
  with (a.out/name).open('x') as f:w=csv.DictWriter(f,fieldnames=fields or list(data[0]));w.writeheader();w.writerows(data)
 if rows:csvwrite('cells.csv',rows)
 med=[]
 for key in sorted({(r['regime'],r['size'],r['batch'],r['n_per_dm']) for r in rows}):
  group=[r for r in rows if (r['regime'],r['size'],r['batch'],r['n_per_dm'])==key]
  if len(group)!=3:continue
  r=group[0].copy();r.pop('block')
  for k in r:
   if isinstance(r[k],(int,float)):r[k]=statistics.median(x[k] for x in group)
  med.append(r)
 if med:csvwrite('medians.csv',med)
 fits=[]
 if state['status']=='complete':
  assert len(rows)==1458 and len(med)==486
  for regime in sorted({r['regime'] for r in med}):
   for label,lo,hi in [('all',64,16384),('small',64,1024),('large',2048,16384)]:
    group=[r for r in med if r['regime']==regime and lo<=r['size']<=hi]
    for unit,key in [('tick','dm_max_ticks')]+([('second','dm_max_seconds')] if valid else []):
     f=fit(group,key);fits.append(dict(regime=regime,size_range=label,unit=unit,block='median_of_blocks',**f))
     for block in range(3):fits.append(dict(regime=regime,size_range=label,unit=unit,block=str(block),**fit([r for r in rows if r['regime']==regime and lo<=r['size']<=hi and r['block']==block],key)))
     train=[r for r in rows if r['regime']==regime and lo<=r['size']<=hi and r['block']<2];test=[r for r in rows if r['regime']==regime and lo<=r['size']<=hi and r['block']==2];f=fit(train,key)
     yy=np.array([r[key] for r in test]);pp=np.array([f['delta']+f['alpha']*r['requests']+f['beta']*r['bytes']+f['gamma']*r['barriers'] for r in test]);f['r2']=float(1-np.sum((yy-pp)**2)/np.sum((yy-yy.mean())**2));f['interpretation']='train_blocks_0_1_test_block_2';f['crossover_bytes']=None;f['alpha_10x_dominance_max_bytes']=None;f['alpha_2x_dominance_max_bytes']=None;fits.append(dict(regime=regime,size_range=label,unit=unit,block='heldout2',**f))
 if fits:csvwrite('fits.csv',fits)
 else:csvwrite('fits.csv',[],['regime','size_range','unit','block','alpha','beta','gamma','r2','interpretation'])
 lines=['# NoC 읽기 요청 비용 결과', '',f'상태: {state["status"]}. 통과한 timing 셀 {sum(r.get("kind")=="timing" and r.get("status")=="pass" for r in state["records"])}/486. 실패/미측정 셀은 campaign 원자료에 보존한다.', '',f'Seconds 변환 calibration 유효: {valid}. 유효하지 않으면 tick 값을 임의 GHz로 변환하지 않는다.', '', '실측은 16 KiB interleaved page와 1,152 KiB/core(2DM) CB를 사용한다. StepTC/WeTriC/TriCore의 작은 page interleave와 동일하다고 주장하지 않는다. 배치는 소프트웨어 발행 수이며 실제 hardware outstanding 수를 계측한 값이 아니다.', '',f'CSV·fit·calibration: `{a.out}`. `medians.csv`는 block 중앙값의 중앙값이다. host wall과 DM-max 시간은 구분한다. α/β/γ는 유효 비용이며 모델 부적합이나 음의 계수도 보존한다.', '', '| 조건 | 크기 범위 | 단위 | α | β | γ | R² | α가 10배 우세한 최대 B |','|---|---|---|---:|---:|---:|---:|---:|']
 for f in fits:
  if f['block']!='median_of_blocks':continue
  lines.append('| '+' | '.join(str(f[k]) for k in ['regime','size_range','unit','alpha','beta','gamma','r2','alpha_10x_dominance_max_bytes'])+' |')
 if not fits:lines+=['','전체 grid가 완료되지 않아 비용 모델을 최종 적합하지 않았다.']
 (a.out/'NOC_MICROBENCH_RESULTS.md').write_text('\n'.join(lines)+'\n');(E/'NOC_MICROBENCH_RESULTS.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':main()
