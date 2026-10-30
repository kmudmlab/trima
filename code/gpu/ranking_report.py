"""완료한 세 block만 순위에 사용한다. TT는 로컬 동결 snapshot 범위를 명시한다."""
import csv,json
from pathlib import Path

def report(out,rows,records,exceptions,snapshot):
    tt=json.loads(snapshot.read_text())
    lookup={(r['graph'],r['family']):r for r in tt['rows']}
    joined=[]
    for r in rows:
        t=lookup.get((r['graph'],r['family']),{})
        joined.append(dict(graph=r['graph'],family=r['family'],gpu_status=r['status'],
            gpu_median_s=r['median_s'],gpu_rank=r['rank'],
            tt_variant=t.get('tt_variant'),tt_median_s=t.get('tt_median_s'),
            tt_rank=t.get('tt_rank'),tt_source=t.get('source'),tt_scope=t.get('scope')))
    (out/'gpu-vs-tt.json').write_text(json.dumps(joined,indent=2,ensure_ascii=False)+'\n')
    with (out/'gpu-vs-tt.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(joined[0]));w.writeheader();w.writerows(joined)
    fmt=lambda v:'—' if v is None else f'{v:.6g}'
    real=[r for r in records if r.get('block') is not None]
    fixture=[r for r in records if r.get('block') is None]
    lines=['# GPU Count 순위 결과','','디스플레이 프로세스가 상주한 상태에서 측정했다. 각 셀의 nvidia-smi-before.txt/xml 및 gpu-state-before.json에 프로세스 목록·GPU 전체/프로세스별 메모리 사용량·조회 시각을 보존했다. GDM 화면 프로세스만 예외로 허용했고 다른 GPU 프로세스가 있으면 대기했다.','',
      'bear RTX 4080에서 카운터 없이 측정했다. 셀마다 새 프로세스, warmup 1회와 측정 3회, '
      '독립 3 block(seed `20261022+block`)이다. 각 block 중앙값의 중앙값으로 순위를 계산했다.',
      '',f'- GPU fixture: {len(fixture)}셀, 통과 {sum(r.get("status")=="pass" for r in fixture)}셀.',
      f'- 실그래프 timing: 실행 {len(real)}셀, 통과 {sum(r.get("status")=="pass" for r in real)}셀.',
      f'- 용량 적용 불가: {len(exceptions)}개 그래프·계열 조합. 원인은 `status.json`에 보존했다.',
      '- GPU 순위는 측정 가능한 계열 사이의 순위다. 적용 불가 계열의 성능은 추정하지 않는다.',
      '- Count는 기존 adapter의 resident_s를 사용한다. 입력 업로드·전처리는 제외하고 '
      'kernel launch·동기화·결과 합산/읽기는 포함한다. TriCore는 여러 chunk의 Count 시간을 합산한다.',
      '- TT는 로컬에서 확보한 완료 suite 변형 중 계열별 최선이다. hash-mix 및 후속 캠페인이 '
      '포함되지 않은 snapshot이므로 전체 최신 최선이라는 뜻은 아니다. WebCC 미완료 값은 비워 둔다.',
      '- GPU와 TT의 timing 범위·동기화 비용은 완전히 동일하지 않다. 순위 비교와 절대 속도 비교를 구분한다.',
      '', '| 그래프 | 계열 | GPU 상태 | GPU 중앙값(s) | GPU 순위 | TT 변형 | TT 중앙값(s) | TT 순위 |',
      '|---|---|---|---:|---:|---|---:|---:|']
    for r in joined:
        lines.append('| '+' | '.join([r['graph'],r['family'],r['gpu_status'],fmt(r['gpu_median_s']),
          str(r['gpu_rank'] or '—'),r['tt_variant'] or '—',fmt(r['tt_median_s']),str(r['tt_rank'] or '—')])+' |')
    lines += ['', '기존 결론의 변경 여부는 TT 최신 결과와 함께 검토한다. 이 표 자체로 GPU/TT의 '
      '계열별 순위 변화 원인을 확정하지 않는다. 후속 카운터 계측에서 메모리 요청·L2 hit·occupancy·warp 효율을 확인한다.','']
    (out/'GPU_RANKING_RESULTS.md').write_text('\n'.join(lines))
