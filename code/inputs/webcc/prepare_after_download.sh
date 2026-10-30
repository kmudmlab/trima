#!/usr/bin/env bash
set -euo pipefail
cd /data0/hmpark/tritt-gpu-20260908/paper_runs/2026-09-27-webcc-ede0
while kill -0 2145410 2>/dev/null; do sleep 10; done
/usr/bin/time -v bash -o pipefail -c 'pigz -dc inputs/sd-arc.gz | OMP_NUM_THREADS=8 ./prepare inputs/webcc.csr 2050000000 > inputs/webcc.structure.json' 2> prepare.log
sha256sum inputs/sd-arc.gz inputs/webcc.csr > inputs/SHA256SUMS
OMP_NUM_THREADS=8 /usr/bin/time -v ./count_reference inputs/webcc.csr > inputs/webcc.reference.json 2> reference.log
./tile_model inputs/webcc.csr 8208 0 > inputs/webcc-fixed-model.json
./tile_model inputs/webcc.csr 8208 1 > inputs/webcc-pool-model.json
python3 - <<'PY'
from pathlib import Path
import json
r=Path('inputs');s=json.loads((r/'webcc.structure.json').read_text());s.update(json.loads((r/'webcc.reference.json').read_text()))
h={line.split()[1]:line.split()[0] for line in (r/'SHA256SUMS').read_text().splitlines()}
s.update(name='webcc',label='WebCC',input_sha256=h['inputs/webcc.csr'],input_bytes=(r/'webcc.csr').stat().st_size,raw_sha256=h['inputs/sd-arc.gz'],source_url='https://data.dws.informatik.uni-mannheim.de/hyperlinkgraph/2012-08/sd-arc.gz',dataset='Common Crawl 2012 complete host graph',orientation='undirected simple graph; remove isolated IDs; ascending (undirected degree, original ID); sorted numeric-forward rows')
(r/'webcc.json').write_text(json.dumps(s,indent=2)+'\n')
print('COMPLETE normalization, CPU count, tile models',flush=True)
PY
