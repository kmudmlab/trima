# Artifact: triangle counting on a many-core accelerator with explicit local memory

Artifact for the paper *Why GPU Rankings Do Not Survive the Move: Triangle Counting on a
Many-Core Accelerator with Explicit Local Memory* (ICDE 2027, Experiment, Analysis, and
Benchmark track).

It contains the code that produced every measurement in the paper, the raw per-cell results,
and scripts that regenerate the paper's generated numbers, tables and figures from those results
alone. Re-running the measurements needs a Tenstorrent Blackhole P150a; checking the paper's
numbers does not.

## Quick start (no accelerator needed)

```sh
tar -xzf results.tar.gz                 # creates results/ (316 MB, about 40,000 small JSON and CSV files)
sha256sum -c results.tar.gz.sha256      # optional
python3 -m pip install matplotlib       # the only dependency (Python 3.10 or later)
python3 paper/make_outputs.py           # numbers, tables and figures -> paper/generated, paper/figures
python3 paper/count_checks.py           # correctness totals of Section IV-C
```

`make_outputs.py` prints the Spearman correlations of Figure 3 and writes:

| Output | Paper |
|---|---|
| `generated/numbers-suite.tex` | numbers quoted as macros in the text (spread statistics of Section IV-D, per-rung effects, ratios) |
| `generated/numbers-gpu.tex` | GPU numbers quoted in the text |
| `generated/ranking.tex`, `families_times.tex`, `abstime.tex` | Tables VI, VII and IX |
| `generated/trisc.tex` | Table V (StepTC supply mode x TRISC consumers) |
| `figures/principle_dist.pdf` | Figure 1 (effect of each rung) |
| `figures/supply_condition.pdf` | Figure 3 (range-supply speedup against request ratio) |
| `figures/cumulative_ladders.pdf` | Figure 4 (cumulative speedup of each ladder) |

`count_checks.py` prints the CPU oracle checks, device fixture runs, profiling and timing runs on
real graphs, count mismatches (zero) and the circular-buffer sizes read back from the device.

## Layout

| Path | Contents |
|---|---|
| `results.tar.gz` | raw results of every campaign the paper uses, one directory per campaign |
| `paper/` | `rawdata.py` (readers), `make_outputs.py`, `count_checks.py` |
| `code/ports/` | baseline ports of StepTC, WeTriC, TriCore and TRUST and their execution variants (range supply, open addressing, probe batching, lockstep search, pruning) |
| `code/ladders/` | the four cumulative ladders: TRUST L0-L4, then scaffolding, resident row pointers (T), TRISC consumers and the second source context for every family, in both supply modes |
| `code/controls/` | control experiments (see the table below) |
| `code/oracles/` | CPU set-intersection oracles and device fixture campaigns |
| `code/gpu/` | GPU drivers and campaigns; StepTC sources; patches for TRUST, TriCore and WeTriC (see Licenses) |
| `code/cpu/gbbs/` | GBBS CPU reference: preparation, patch, runner |
| `code/inputs/` | graph preparation (orientation, CSR) and the WebCC pipeline |

Each `code/` directory is a byte-identical copy of the files a campaign ran; the cell manifests
in `results/` pin their SHA-256 values. Orchestration that only moved files between hosts is
left out.

## Results

Every campaign directory holds one directory per cell with `config.json` (input, variant,
expected triangle count) and `summary.json` (status, median time, owner-count check), and for
profiling cells `profile.json` (read-request and byte counters). Timing cells follow one
protocol: each cell runs in a fresh process, one warm-up and three measured runs, in three
blocks with a seeded order; a cell's time is the median of its three block medians. A cell
passes only if the triangle count and every owner's count equal the reference.

| Paper | `results/` | `code/` |
|---|---|---|
| Table IV, Fig. 1: baselines and execution variants on the 14 suite graphs | `suite-v1` | `ports/direct`, `ports/trust` |
| Fig. 3: request ratio and range-supply speedup (with the road networks) | `suite-v1`, `roads-v1`, `roads-v1-inputs` | `ports/direct-roads` |
| Request-counter validation | `cpu-replay-v1`, `rowptr-replay-v1`, `noc-microbench-v1(-analysis)` | `controls/cpu-request-replay`, `controls/request-microbenchmark`, `ladders/ends/replay` |
| Locality sweep (tie-breaking probability p) | `locality-sweep-v1`, `locality-sweep-v1-requests` | `controls/locality-sweep` |
| Page cache against range supply at equal SRAM | `page-range-control-v1` | `controls/page-range-2x2` |
| Lockstep binary search | `lockstep-v1` | `ports/direct-lockstep` |
| Hash functions (multiply-shift, two-round mix) | `hash-multiply-shift-v1`, `hash-two-round-mix-v1`, `hash-cpu-*` | `controls/hash` |
| Table V: TRISC consumers x supply mode | `trisc-factorial-v1` | `controls/trisc-factorial` |
| Order of the pruning subsets | `order-subsets-v1` | `controls/order-subsets` |
| Prefetch control | `prefetch-control-v1` | `controls/prefetch` |
| Tables II and VIII, Fig. 1, Fig. 4: ladders, rung effects, cumulative speedup | `ladders-v1`, `ladders-v1-block0`, `ladder-ends-v1` | `ladders/` |
| Table IX: CSR upload time | `upload-v1` | `controls/upload` |
| Optimization levels with counters on and off, tuning, page size, SRAM capacity | `counters-on-v1`, `counters-off-v1`, `tuning-v1`, `tuning-page-size-v1`, `sram-capacity-v1`, `range-check-v1` | `controls/counters-off`, `controls/tuning-and-capacity` |
| Table VI: GPU ranking (RTX 4080, GTX 1660), Nsight metrics, WeTriC tail ablation | `gpu-rtx4080-v1`, `gpu-rtx4080-roads-v1`, `gpu-rtx4080-metrics-v1`, `gpu-gtx1660-v1`, `gpu-wetric-tail-off-v1` | `gpu/` |
| CPU reference (GBBS) | `cpu-gbbs-v1` | `cpu/gbbs` |
| Section IV-C: correctness totals | all of the above, `correctness/` | `oracles/` |

Numbers quoted in the text that the scripts do not generate are read from the `summary.json`
or `comparison.json` files of the campaign named in this table. The two-round-mix campaign keeps
only its per-graph `comparison.json` files.

## Hardware and software of the measurements

- Tenstorrent Blackhole P150a, firmware 19.11.0, TT-NN 0.76.0 with the bundled RISC-V GCC 15.1;
  host AMD Ryzen 5 3600 (6 cores), 31 GiB, Ubuntu 22.04 (kernel 6.8). Circular buffers stay
  within 1,392 KiB per core in every study.
- GPU references: RTX 4080 (driver 580.173.02, CUDA 12.1) in a separate host; GTX 1660 (6 GB,
  driver 550.107.02) in the accelerator host.
- CPU reference: GBBS at commit `dbd1dcad582c0a316c5ba0d5524319d596dd82da`
  (`results/cpu-gbbs-v1/environment.json` has the host, build flags and patch).

## Inputs

Graphs are not included. All graphs are oriented as simple undirected graphs without isolated
vertices (Table III of the paper lists n, m and the triangle counts every cell checks against).

- SNAP: Facebook, NotreDame, Stanford, Google, WikiTalk, BerkStan, Skitter, Patents, com-LJ,
  soc-LJ, com-Orkut, Friendster, roadNet-PA, roadNet-TX, roadNet-CA (https://snap.stanford.edu/data/).
- LAW: Hollywood (hollywood-2009, https://law.di.unimi.it/datasets.php).
- WebCC: Common Crawl 2012 host graph,
  https://data.dws.informatik.uni-mannheim.de/hyperlinkgraph/2012-08/sd-arc.gz.

`code/inputs/prepare_graph.cpp` (and `inputs/mm/` for Matrix Market files) writes the CSR;
`code/inputs/webcc/` is the WebCC pipeline. The SHA-256 of every prepared input is recorded in
`results/suite-v1/preflight.json` and `results/roads-v1-inputs/inputs-v1/*.json`.

## Re-running on a P150a

The campaign runners are the scripts under each `code/.../campaign` directory. They are kept as
run, so they contain the absolute paths and host names of our machines (for example
`/data0/...` and SSH aliases); set these to your own input and output locations before running.
Device runs need TT-NN 0.76.0 and exclusive use of the card; GPU kernels for TRUST, TriCore and
WeTriC are rebuilt with `code/gpu/fetch_upstream.sh` (below).

## Licenses

- StepTC is MIT-licensed; its sources and license are in `code/gpu/steptc/`.
- TRUST, TriCore and WeTriC publish no license, so only patches are included.
  `code/gpu/fetch_upstream.sh` clones the authors' repositories at the pinned commits
  (TRUST `90845c6d`, TriCore `adcbf043`, WeTriC `f0c80447`), applies
  `code/gpu/upstream-patches/*.patch` and checks the result against `code/gpu/SOURCES.sha256`.
- GBBS is not included; `code/cpu/gbbs/gbbs-timing-print.patch` applies to the commit above.
