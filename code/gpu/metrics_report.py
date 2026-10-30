"""Nsight Compute raw CSV를 검증하고 분자/분모를 합산한다."""
import csv,io,json,math,re,statistics
from pathlib import Path

def replay_metadata(text):
    """Application replay 로그와 raw의 kernel replay 수를 혼동하지 않는다."""
    passes=[int(x) for x in re.findall(r'Application replay pass\s+(\d+)',text)]
    unique=sorted(set(passes))
    if not unique or unique!=list(range(1,max(unique)+1)):
        raise ValueError('Application replay pass sequence missing or incomplete')
    return dict(application_replay_pass_numbers=unique,
                application_replay_pass_count=len(unique),
                application_replay_log_events=len(passes))


def summarize_cell(path,required):
    text=path.read_text()
    if 'ERR_NVGPUCTRPERM' in text or '==ERROR==' in text:
        raise ValueError('NCU error in CSV output')
    rows=list(csv.reader(io.StringIO(text)))
    start=next((i for i,r in enumerate(rows) if 'ID' in r and 'Kernel Name' in r
                and (('Metric Name' in r and 'Metric Value' in r) or any(m in r for m in required))),None)
    if start is None:raise ValueError('NCU raw CSV header missing')
    header=rows[start]
    if len(header)!=len(set(header)):raise ValueError('Duplicate CSV column')
    layout='long' if 'Metric Name' in header else 'wide'
    kernels={};units=None
    expected_units={m:('%' if m.endswith('.pct') or m=='sm__warps_active.avg.pct_of_peak_sustained_active' else
                       'sector' if m.startswith('lts__') or m.startswith('l1tex__t_sectors') else
                       'request' if m.startswith('l1tex__t_requests') else 'inst') for m in required}
    def add(row,metric,value,unit):
        key=(row.get('ID'),row.get('Kernel Name'))
        if not all(x is not None and x!='' for x in key):raise ValueError('Kernel identity missing')
        value=float(value.replace(',',''))
        if not math.isfinite(value) or value<0:raise ValueError('Nonfinite/negative metric')
        if unit!=expected_units[metric]:raise ValueError('Unexpected metric unit: '+metric+' '+str(unit))
        item=kernels.setdefault(key,dict(id=key[0],kernel=key[1],metrics={},units={}))
        if metric in item['metrics']:raise ValueError('Duplicate metric for launch')
        item['metrics'][metric]=value;item['units'][metric]=unit
    if layout=='wide' and set(required)-set(header):
        raise ValueError('Missing metric columns: '+str(set(required)-set(header)))
    for fields in rows[start+1:]:
        if not fields or all(not x for x in fields):continue
        if len(fields)!=len(header):raise ValueError('Malformed CSV row width')
        row=dict(zip(header,fields))
        if layout=='long':
            metric=row.get('Metric Name')
            if metric in required:add(row,metric,row['Metric Value'],row.get('Metric Unit'))
        else:
            if not row['ID']:
                if kernels or units is not None:raise ValueError('Unexpected extra units row')
                units=row;continue
            if units is None:raise ValueError('Wide CSV units row missing')
            for metric in required:add(row,metric,row[metric],units[metric])
            key=(row['ID'],row['Kernel Name'])
            # NCU exports this separately from stdout application replay passes.
            if 'profiler__replayer_passes' in row:
                v=float(row['profiler__replayer_passes'].replace(',',''))
                if not math.isfinite(v) or v<0 or not v.is_integer():raise ValueError('Invalid raw replay count')
                kernels[key]['profiler_replayer_passes']=int(v)
    if not kernels:raise ValueError('No profiled Count kernels')
    for k in kernels.values():
        missing=set(required)-set(k['metrics'])
        if missing:raise ValueError('Missing metrics: '+str(missing))
    totals={m:sum(k['metrics'][m] for k in kernels.values()) for m in required if m.endswith('.sum')}
    def ratio(num,den,scale=1):return scale*totals[num]/totals[den] if totals[den] else None
    return dict(csv_layout=layout,launch_count=len(kernels),kernels=list(kernels.values()),summed_counters=totals,
      l2_sector_hit_pct=ratio('lts__t_sectors_lookup_hit.sum','lts__t_sectors.sum',100),
      global_load_sectors_per_request=ratio('l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum','l1tex__t_requests_pipe_lsu_mem_global_op_ld.sum'),
      warp_execution_efficiency_pct=ratio('smsp__thread_inst_executed.sum','smsp__inst_executed.sum',100/32),
      achieved_occupancy='per-kernel only; no unweighted multi-kernel average')

def report(out,records):
    rows=[]
    for r in records:
        if r.get('block') is None or r.get('status')!='pass':continue
        d=json.loads((out/r['name']/'derived-metrics.json').read_text())
        rows.append(dict(graph=r['graph'],family=r['family'],block=r['block'],
          **{k:d[k] for k in ['launch_count','l2_sector_hit_pct','global_load_sectors_per_request','warp_execution_efficiency_pct']}))
    (out/'metrics-by-cell.json').write_text(json.dumps(rows,indent=2)+'\n')
    with (out/'metrics-by-cell.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    lines=['# GPU 카운터 결과','','디스플레이 프로세스가 상주한 상태에서 측정했다. 각 셀의 nvidia-smi-before.txt/xml 및 gpu-state-before.json에 프로세스 목록·GPU 전체/프로세스별 메모리 사용량·조회 시각을 보존했다. GDM 화면 프로세스만 예외로 허용했고 다른 GPU 프로세스가 있으면 대기했다.','',
      'bear에서 timing 순위 완료 뒤 application replay로 계측했다. cache-control과 clock-control은 none이다.',
      f'fixture pilot {sum(r.get("block") is None for r in records)}셀, 실그래프 profile {len(rows)}셀을 통과했다.',
      'Count에 속한 launch를 모두 수집한다. 비율은 launch별 분자·분모를 합산한 뒤 계산하고, 아래에는 독립 3 block의 중앙값을 쓴다.',
      'Occupancy는 각 셀의 derived-metrics.json에 kernel별로 보존한다. 서로 다른 kernel의 비율을 단순 평균하지 않는다.',
      '프로파일 wall time과 replay pass는 각 summary.json에 있으며 논문의 Count timing으로 사용하지 않는다.',
      '', '| 그래프 | 계열 | L2 hit (%) | global-load sectors/request | warp execution efficiency (%) |',
      '|---|---|---:|---:|---:|']
    for key in sorted({(r['graph'],r['family']) for r in rows}):
        group=[r for r in rows if (r['graph'],r['family'])==key]
        if len(group)!=3:raise ValueError('Incomplete profile blocks: '+str(key))
        vals=[]
        for metric in ['l2_sector_hit_pct','global_load_sectors_per_request','warp_execution_efficiency_pct']:
            v=[r[metric] for r in group];vals.append('NA' if any(x is None for x in v) else f'{statistics.median(v):.6g}')
        lines.append('| '+' | '.join([*key,*vals])+' |')
    lines+=['','GPU와 TT의 요청 단위는 다르다. 이 표만으로 GPU→TT 포팅 원칙의 인과관계를 확정하지 않는다.','']
    (out/'GPU_METRICS_RESULTS.md').write_text('\n'.join(lines))
