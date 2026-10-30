#!/usr/bin/env python3
"""Correctness totals of Section IV-C, counted from results/.

Device runs: every cell directory with a config.json on the Tenstorrent device. A run passes when
its summary says so; the runners only report a pass when the triangle count (and, for per-owner
runners, every owner's count) equals the reference, and we check count == expected again here.
A run is a fixture run when its input is a fixture graph, a profiling run when counters are on,
and a timing run otherwise. Locality-sweep graphs are generated, not real graphs, and are counted
in neither total; the request microbenchmark counts no triangles and is skipped; GPU and CPU
references are not device runs.

CPU oracle checks: one check is one (fixture, engine count, configuration) comparison against the
set-intersection oracle in a passing CPU report. Records of excluded algorithms are dropped:
BTC (mode 4) in the early reports and the TriMA payload half of the hash source-model checks.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawdata import GRAPHS, ROADS, RES, load  # noqa: E402

REAL = GRAPHS + ROADS
SKIP_TOP = {"noc-microbench-v1", "gpu-rtx4080-v1", "gpu-rtx4080-metrics-v1", "gpu-rtx4080-roads-v1",
            "gpu-gtx1660-v1", "gpu-wetric-tail-off-v1"}
EXCLUDED_MODES = re.compile(r"^(btc|trima|polak|notrisc)")
GRAPH_RE = re.compile("|".join(sorted((re.escape(g) for g in REAL), key=len, reverse=True)))


def graph_of(cfg, cell):
    """The real graph a cell ran on, 'synthetic' for generated sweep graphs, None for a fixture."""
    stem = Path(str(cfg.get("input") or "")).name
    for text in (stem, cell.name):
        if "grid2d" in text:
            return "synthetic"
        for m in GRAPH_RE.finditer(text):
            a, b = m.start(), m.end()
            if (a == 0 or not text[a - 1].isalnum()) and (b == len(text) or not text[b].isalnum()):
                return m.group(0)
    return None


def is_profile(cfg, summ):
    return (cfg.get("profile") is True or str(cfg.get("counters")) == "1" or str(summ.get("counters")) == "1"
            or str(cfg.get("profile_io")) == "1")


def cb_bytes(cell, cfg, summ):
    """(bytes read back from the device, bytes the host declared) of a cell's circular buffers."""
    readback = []
    for p in cell.glob("cb-allocation*.json"):
        a = load(p)
        if "total_cb_bytes" in a:
            readback.append(a["total_cb_bytes"])
    if (cell / "samples.jsonl").exists():
        for line in (cell / "samples.jsonl").read_text(errors="replace").splitlines():
            if '"cb_discovery"' in line:
                readback.append(json.loads(line)["total_bytes"])
    declared = [v for v in (cfg.get("l1_bytes"), cfg.get("l1_design_bytes"), summ.get("l1_bytes"))
                if isinstance(v, (int, float))]
    return max(readback, default=None), max(declared, default=None)


def device_runs():
    tally, cells = Counter(), []
    for cfg_path in sorted(RES.rglob("config.json")):
        cell = cfg_path.parent
        if cell.relative_to(RES).parts[0] in SKIP_TOP:
            continue
        cfg = load(cfg_path)
        summ = load(cell / "summary.json") if (cell / "summary.json").exists() else {}
        if EXCLUDED_MODES.match(str(cfg.get("mode", summ.get("mode", "")))):
            continue
        g = graph_of(cfg, cell)
        kind = "fixture" if g is None else "synthetic" if g == "synthetic" else \
            "profile" if is_profile(cfg, summ) else "timing"
        status = summ.get("status", "no summary")
        expected = cfg.get("expected", cfg.get("expected_count"))
        if status == "pass" and "count" in summ and expected is not None and summ["count"] != expected:
            status = "count mismatch"
        tally[(kind, status)] += 1
        cells.append((str(cell.relative_to(RES)), kind, status, *cb_bytes(cell, cfg, summ)))
    return tally, cells


def cpu_checks():
    out = {}
    for d in sorted((RES / "correctness" / "cpu").iterdir()):
        f = next(d.glob("*.json"))
        rep = load(f)
        assert rep.get("status") == "pass", f
        if "records" in rep:
            recs = [r for r in rep["records"] if r.get("status", "pass") == "pass" and str(r.get("mode")) != "4"]
            out[d.name] = len(recs)
        elif "semantic_cells" in rep:        # TRISC factorial CPU model
            out[d.name] = rep["semantic_cells"]
        else:                                # hash source models: TRUST half only (trima in {0, 1})
            out[d.name] = rep["steptc_checks"] + rep["source_semantic_checks"] // 2
    return out


def main():
    tally, cells = device_runs()
    cpu = cpu_checks()
    for k, v in sorted(tally.items()):
        print(f"{k[0]:10s} {k[1]:16s} {v:6d}")
    bad = [c[:3] for c in cells if c[2] != "pass"]
    for c in bad:
        print("  not passed:", c)
    for k, v in cpu.items():
        print(f"cpu {k:48s} {v:6d}")
    fixture = tally[("fixture", "pass")]
    graph = tally[("profile", "pass")] + tally[("timing", "pass")]
    print(f"\nCPU oracle checks           {sum(cpu.values()):,}")
    print(f"device fixture runs         {fixture:,}")
    print(f"profiling and timing runs   {graph:,} "
          f"({tally[('profile', 'pass')]:,} profile + {tally[('timing', 'pass')]:,} timing)")
    print(f"count mismatches            {sum(v for (k, s), v in tally.items() if s == 'count mismatch')}")
    readback = [c[3] for c in cells if c[3] is not None]
    declared = [c[4] for c in cells if c[3] is None and c[4] is not None]
    print(f"\ncells with CB read back     {len(readback):,}, max {max(readback) / 1024:,.0f} KiB per core")
    print(f"other cells, declared max   {max(declared) / 1024:,.0f} KiB per core "
          f"({len(declared):,} cells; {sum(c[3] is None and c[4] is None for c in cells)} without either)")


if __name__ == "__main__":
    main()
