#!/usr/bin/env python3
"""Read-only task-5 input/capacity audit. Does not import ttnn or open a device.

Run on tt using /home/dmlab/eptq-tt-venv/bin/python; stdout is one JSON document.
Sizes below are allocation calculations, NOT measured device allocations or timing.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path('/data/dmlab/trima_full_comparison_20260929/artifact/inputs')
GRAPHS = 'fb notredame stanford google berkstan wikitalk skitter patents comlj soclj hollywood orkut friendster webcc'.split()
SOC = Path('/home/dmlab/eptq-tt-venv/lib/python3.10/site-packages/ttnn/tt_metal/soc_descriptors/blackhole_140_arch.yaml')
L1_LIMIT = 1392 * 1024


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(16 << 20), b''):
            h.update(block)
    return h.hexdigest()


def align(x, size):
    return (x + size - 1) // size * size


def trust_l1(cap, oa, direct, page):
    cap = max(32, align(cap, 32))
    slots = 80 * 1024 // page
    sizes = [0 if oa else 4096, 0 if oa else 1024*100*4,
             65536 if oa else 0, cap*4 if oa else 0, (cap+32)*4,
             align(slots, 32)*4, 80*1024, 8192 if direct else 128,
             65536 if direct else 0, 4096]
    return 2 * align(sum(align(x, 64) for x in sizes), 4096)


def direct_l1(cap, mode, page, oa=False):
    cap = max(32, cap)
    slots = 96*1024 // page
    if mode == 'steptc':
        words = 2*cap+2049
    elif mode in ('wetric', 'tricore'):
        words = cap+32
    elif mode == 'steptc-direct':
        parts = [16384, 2048, 256, 96, cap+32, 64]
        parts += [16384, cap] if oa else [1022, 1022, cap]
        words = sum(align(x, 16) for x in parts)
    elif mode == 'wetric-direct':
        words = sum(align(x, 16) for x in [16384, 2048, 256, 64, 64, 64, cap+32])
    else:
        words = sum(align(x, 16) for x in [16384, 2048, 256, 64, 64, 32, cap+32, 32, cap+16])
    return 2 * align(96*1024 + align(slots, 32)*4 + words*4, 4096)


def dram_bound(n, m, family):
    # Account for all auxiliary allocated words, even unused StepTC task tail.
    arrays = [n+1, m]
    if family == 'steptc':
        arrays += [n+1+m]
    elif family == 'wetric':
        arrays += [2*(n+1)]
    elif family == 'tricore':
        arrays += [max(m, 32)]
    # Conservative 8-bank, 16KiB page alignment per <=256MiB tensor chunk.
    # Includes output/reduction/runtime margin, not a free-memory observation.
    allocation = sum(align(min(256 << 20, size-offset), 8*16384)
                     for words in arrays for size in [words*4]
                     for offset in range(0, max(1, size), 256 << 20))
    return allocation + (64 << 20)


def main():
    import yaml
    soc = yaml.safe_load(SOC.read_text())
    owners = subprocess.run(['fuser', '/dev/tenstorrent/0'], capture_output=True, text=True)
    report = dict(status='in_progress', device_opened=False,
                  hardware=dict(card=Path('/sys/class/tenstorrent/tenstorrent!0/tt_card_type').read_text().strip(),
                                soc_path=str(SOC), soc_sha256=sha(SOC),
                                descriptor_dram_channels=len(soc['dram']),
                                descriptor_bank_bytes=soc['dram_bank_size'],
                                descriptor_total_dram_bytes=len(soc['dram'])*soc['dram_bank_size'],
                                descriptor_l1_bytes=soc['worker_l1_size'],
                                experiment_l1_limit_bytes=L1_LIMIT,
                                conservative_dram_budget_bytes=30 << 30,
                                fuser_returncode=owners.returncode, fuser_stdout=owners.stdout,
                                fuser_stderr=owners.stderr), graphs=[])
    for name in GRAPHS:
        path = ROOT / (name+'.json')
        meta = json.loads(path.read_text())
        csr = Path(meta['path'])
        a = np.memmap(csr, dtype='<u4', mode='r')
        n, m = map(int, a[:2])
        rp = a[2:n+3]
        degree = np.diff(rp.astype(np.int64))
        cap = int(degree.max(initial=0))
        digest = sha(csr)
        checks = dict(input_hash=digest == meta['input_sha256'],
                      dimensions=n == meta['n'] and m == meta['m'],
                      file_bytes=csr.stat().st_size == 4*(n+m+3) == meta['input_bytes'],
                      max_degree=cap == meta['max_degree'],
                      csr_offsets=int(rp[0]) == 0 and int(rp[-1]) == m and bool(np.all(degree >= 0)),
                      signed32=n < 2**31 and m < 2**31,
                      metadata_count=sum(meta['engine_counts']) == meta['count'])
        variants = []
        for v, oa, direct, page in [('B0',0,0,1024), ('B2',1,0,1024), ('B3',1,1,16384), ('B4',1,1,16384)]:
            variants.append(dict(family='trust', variant=v, page_bytes=page,
                                 l1_bytes=trust_l1(cap, oa, direct, page)))
        for family, vs, page in [('steptc',['base','D1','D2','D3'],1024),
                                ('wetric',['base','D1','D5'],256),
                                ('tricore',['base','D1'],256)]:
            for v in vs:
                variants.append(dict(family=family, variant=v, page_bytes=page,
                                     l1_bytes=direct_l1(cap, family if v=='base' else family+'-direct', page,
                                                       family=='steptc' and v in ('D2','D3'))))
        for v in ['base', 'notrisc']:
            variants.append(dict(family='trima', variant=v, page_bytes=16384, l1_bytes=816*1024))
        for v in variants:
            v['dram_allocation_bound_bytes'] = dram_bound(n,m,v['family'])
            v['static_capacity_pass'] = (v['l1_bytes'] <= L1_LIMIT and
                                         v['dram_allocation_bound_bytes'] <= 30 << 30)
            v['runtime_allocation_verified'] = False
        entry = dict(graph=name, input_path=str(csr), metadata_path=str(path), metadata_sha256=sha(path),
                     n=n,m=m,max_degree=cap,input_bytes=csr.stat().st_size,
                     input_sha256=digest, expected_input_sha256=meta['input_sha256'],
                     expected_count=meta['count'],checks=checks,
                     rows_gt128=int(np.count_nonzero(degree>128)),
                     rows_gt1024=int(np.count_nonzero(degree>1024)),
                     variants=variants)
        report['graphs'].append(entry)
        print(name+': '+('pass' if all(checks.values()) else 'STOP'), file=sys.stderr, flush=True)
        if not all(checks.values()) or not all(v['static_capacity_pass'] for v in variants):
            report['status']='stop_requires_user_review'
            print(json.dumps(report, indent=2))
            return 2
        del a,rp,degree
    report['status']='static_preflight_pass_runtime_unverified'
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
