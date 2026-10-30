#!/usr/bin/env python3
"""Regenerate the paper's generated numbers, tables and figures from results/ only.

Writes generated/numbers-suite.tex, generated/numbers-gpu.tex, generated/{abstime,families_times,
ranking,trisc}.tex and figures/{principle_dist,supply_condition,cumulative_ladders}.pdf.
"""
import math
import statistics as st
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import rawdata as R
from rawdata import EDGES, FAM, LABELS, ROADS

HERE = Path(__file__).resolve().parent
GEN, FIG = HERE / "generated", HERE / "figures"
GAIN, LOSS = 1.03, 0.97
PORTS = ["StepTC", "WeTriC", "TriCore"]
NAME = {"trust": "TRUST", "tricore": "TriCore", "wetric": "WeTriC", "steptc": "StepTC"}

FAMILY_STYLE = {"StepTC": ("#2a78d6", "o"), "WeTriC": ("#eb6834", "s"), "TriCore": ("#1baf7a", "^"),
                "TRUST": ("#eda100", "D")}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d9d8d4"
ROWS = [("prune", "Pruning"), ("supply", "Range supply"), ("oa", "Open addressing"),
        ("probe", "Hash probe\nbatching"), ("lockstep", "Lockstep\nbinary search"),
        ("scaffold", "Consumer\nscaffolding"), ("rowptr", "Resident row\npointers (T)"),
        ("trisc", "TRISC\nconsumers"), ("ctx", "Second source\ncontext")]
MACRO_NAME = {"supply": "Supply", "oa": "Oa", "probe": "Probe", "lockstep": "Lockstep"}
T40_MODES = ("range", "cache")
T40_RUNGS = ("D-end", "plus-T", "plus-TRISC", "plus-context")
TRISC_ANCHORS = {"stanford", "comlj", "orkut", "hollywood"}  # StepTC anchors = factorial R1 (TRISC on)


def fmt(x, nd=2):
    return f"{x:.{nd}f}"


def sig(x):
    """Three significant digits, no exponent."""
    if x >= 100: return f"{x:.0f}"
    if x >= 10: return f"{x:.1f}"
    if x >= 1: return f"{x:.2f}"
    return f"{x:.{2 - math.floor(math.log10(x))}f}"


def category(v):
    return "gain" if v > GAIN else "loss" if v < LOSS else "neutral"


# ---------------------------------------------------------------- suite effects (D rungs, TRUST B rungs)

COMPARISONS = [  # (principle, family, campaign kind, reference (family, variant), variant)
    ("supply", "StepTC", "direct", ("steptc", "base"), ("steptc", "D1-direct")),
    ("supply", "WeTriC", "direct", ("wetric", "base"), ("wetric", "D1-direct")),
    ("supply", "TriCore", "direct", ("tricore", "base"), ("tricore", "D1-direct")),
    ("supply_page", "TRUST", "source", (None, "B2"), (None, "B3")),
    ("oa", "StepTC", "direct", ("steptc", "D1-direct"), ("steptc", "D2-oa")),
    ("probe", "StepTC", "direct", ("steptc", "D2-oa"), ("steptc", "D3-oa-w4")),
    ("probe", "TRUST", "source", (None, "B3"), (None, "B4")),
    ("lockstep", "WeTriC", "direct", ("wetric", "D1-direct"), ("wetric", "D5-bl4")),
]
FAMILY_VARIANTS = {"StepTC": ("direct", "steptc", ["base", "D1-direct", "D2-oa", "D3-oa-w4"]),
                   "WeTriC": ("direct", "wetric", ["base", "D1-direct", "D5-bl4"]),
                   "TriCore": ("direct", "tricore", ["base", "D1-direct"]),
                   "TRUST": ("source", None, ["B0", "B2", "B3", "B4"])}


def suite():
    """Effects of the suite rungs, every timed suite variant, and the spread of the three block medians."""
    effects, times, spreads = [], [], {}
    for g in R.GRAPHS:
        status = {k: R.suite_campaign(g, k) for k in ("direct", "source")}
        status = {k: (d, R.load(d / "status.json")) for k, d in status.items() if d}

        def blocks(kind, key):
            if kind not in status:
                return None
            b = R.block_medians_status(status[kind][1], *key)
            if not b or len(b) != 3:
                return None
            spreads[(status[kind][0].name, *key)] = (max(b.values()) - min(b.values())) / st.median(b.values())
            return b
        for p, fam, kind, ref, var in COMPARISONS:
            br, bv = blocks(kind, ref), blocks(kind, var)
            if br and bv:
                effects.append({"graph": g, "label": LABELS[g], "principle": p, "family": fam,
                                "speedup": st.median(br.values()) / st.median(bv.values()),
                                "speedup_blocks": [br[k] / bv[k] for k in sorted(br, key=str)]})
        for fam, (kind, key, variants) in FAMILY_VARIANTS.items():
            for v in variants:
                b = blocks(kind, (key, v))
                if b:
                    times.append({"graph": g, "family": fam, "variant": v, "t": st.median(b.values())})
    return effects, times, spreads


# ---------------------------------------------------------------- ladders

def anchor_time(g, f, frozen, suite_times):
    """Anchor of a family: the frozen earlier port, or for TriCore the faster of it and its range port."""
    if f == "tricore":
        d1 = next((t["t"] for t in suite_times if t["graph"] == g and t["family"] == "TriCore"
                   and t["variant"] == "D1-direct"), None)
        return min(frozen, d1) if d1 else frozen
    return frozen


def t40_trust(x, rung):
    vs = [x.get(("trust", f"{m}-{rung}")) for m in T40_MODES]
    vs = [v for v in vs if v]
    return min(vs) if vs else None


def t40_end(x, f):
    if f == "trust":
        return min(v for (ff, vv), v in x.items() if ff == "trust" and vv not in ("base", "anchor"))
    return min(v for (ff, vv), v in x.items() if ff == f and vv != "anchor")


def ladder_effects(effects, suite_times, lad, t40):
    out = [e for e in effects if e["principle"] in ("supply", "oa", "probe", "lockstep")
           and e["family"] in PORTS]
    ratio = lambda a, b: a / b if a and b else None

    def add(g, key, fam, v):
        if v:
            out.append({"graph": g, "label": LABELS.get(g, g), "principle": key, "family": fam, "speedup": v})
    for g, x in lad["trust"].items():
        for key, a, b in (("prune", "L0", "L1"), ("oa", "L1", "L2"), ("supply", "L2", "L3"), ("probe", "L3", "L4")):
            add(g, key, "TRUST", ratio(x.get(a), x.get(b)))
    for g, x in t40.items():
        add(g, "scaffold", "TRUST", ratio(x[("trust", "anchor")], t40_trust(x, "D-end")))
        for m in T40_MODES:
            y = lambda r: x.get(("trust", f"{m}-{r}"))
            add(g, "rowptr", "TRUST", ratio(y("D-end"), y("plus-T")))
            add(g, "trisc", "TRUST", ratio(y("plus-T"), y("plus-TRISC")))
            add(g, "ctx", "TRUST", ratio(y("plus-TRISC"), y("plus-context")))
    for f, rows in lad["other"].items():
        for g, x in rows.items():
            ends = [x[s]["D-end"] for s in T40_MODES if x[s].get("D-end")]
            ref = x["range"].get("anchor")
            if ref:
                ref = anchor_time(g, f, ref, suite_times)
            if f == "steptc" and g in TRISC_ANCHORS:  # anchor already uses TRISC: compare without it
                ref = min(t["t"] for t in suite_times if t["graph"] == g and t["family"] == "StepTC")
            if ends and ref:
                add(g, "scaffold", FAM[f], ref / min(ends))
            for s in T40_MODES:
                y = x[s]
                add(g, "rowptr", FAM[f], ratio(y.get("D-end"), y.get("plus-T")))
                add(g, "trisc", FAM[f], ratio(y.get("plus-T"), y.get("end")))
                add(g, "ctx", FAM[f], ratio(y.get("end"), y.get("plus-context")))
    return out


def all_times(suite_times, lad, t40):
    """Every timed variant of every family: suite, ladder ends, hash ports, TRISC factorial, roads."""
    out = list(suite_times)
    out += [{"graph": g, "family": "TRUSTEnd", "variant": "end", "t": t40_end(x, "trust")} for g, x in t40.items()]
    for g, x in t40.items():
        out += [{"graph": g, "family": FAM[f], "variant": f"t40-{v}", "t": t} for (f, v), t in x.items() if f != "trust"]
    out += [{"graph": g, "family": f, "variant": v, "t": t} for g, f, v, t in R.hash_port_times()]
    for g, x in R.trisc_factorial().items():
        out += [{"graph": g, "family": "StepTC", "variant": f"trisc-{v}", "t": t} for v, t in x.items()]
    for f, graphs in lad["other"].items():
        for g, x in graphs.items():
            end = "plus-context" if f == "steptc" else "end"
            out += [{"graph": g, "family": FAM[f], "variant": f"composed-{m}", "t": x[m][end]}
                    for m in T40_MODES if x[m].get(end)]
    out += [{"graph": g, "family": FAM[f], "variant": v, "t": t} for (g, f, v), t in R.road_times().items()]
    return out


def best_times(times):
    best = {}
    for t in times:
        k = (t["graph"], t["family"])
        if k not in best or t["t"] < best[k]["t"]:
            best[k] = t
    return best


# ---------------------------------------------------------------- numbers-suite.tex

def numbers_suite(effects, times, spreads, lad, t40, suite_times, add):
    graphs = sorted({e["graph"] for e in effects})
    add("SuiteGraphs", len(graphs))
    groups = defaultdict(list)
    for e in effects:
        if e["principle"] in MACRO_NAME:
            groups[(e["principle"], e["family"])].append(e)
    for (p, fam), es in sorted(groups.items()):
        s = sorted(x["speedup"] for x in es)
        base = f"Suite{MACRO_NAME[p]}{fam}"
        add(base + "N", len(s))
        add(base + "Min", fmt(s[0], 3 if s[0] < 1 else 2))
        add(base + "Med", fmt(st.median(s)))
        add(base + "Max", fmt(s[-1]))
        losses = [x["label"] for x in sorted(es, key=lambda x: x["speedup"]) if x["speedup"] < LOSS]
        add(base + "LossGraphs", ", ".join(losses) if losses else "none")
    scalar = [e["speedup"] for e in effects if e["principle"] == "supply"]
    add("SuiteSupplyAllN", len(scalar))
    add("SuiteSupplyAllMin", fmt(min(scalar), 3 if min(scalar) < 1 else 2))
    add("SuiteSupplyAllMed", fmt(st.median(scalar)))
    add("SuiteSupplyAllMax", fmt(max(scalar)))
    add("SuiteSupplyAllLosses", sum(x < LOSS for x in scalar))
    # Spread of the three block medians and of the three per-block effects.
    sp = sorted(spreads.values())
    add("SpreadN", len(sp))
    add("SpreadMed", fmt(100 * st.median(sp), 2))
    add("SpreadMaxNoFb", fmt(100 * max(v for k, v in spreads.items() if not k[0].startswith("fb-")), 1))
    add("SpreadAboveThree", sum(v > 0.03 for v in sp))
    rel = sorted(((max(b) - min(b)) / e["speedup"], e["graph"]) for e in effects
                 if len(b := e["speedup_blocks"]) == 3)
    add("EffectRangeN", len(rel))
    add("EffectRangeMed", fmt(100 * st.median(r for r, _ in rel), 2))
    add("EffectRangeMaxNoFb", fmt(100 * max(r for r, g in rel if g != "fb"), 1))
    add("EffectCategoryFlips", sum(len({category(x) for x in e["speedup_blocks"]}) > 1
                                   for e in effects if len(e["speedup_blocks"]) == 3))
    # TRUST's ladder end against the fastest variant of the other families (losses: road networks).
    best = best_times(times)
    ratios = []
    for g in sorted({g for g, f in best if f == "TRUSTEnd"}, key=EDGES.get):
        port = min((best[(g, f)] for f in PORTS if (g, f) in best), key=lambda t: t["t"])
        ratios.append(port["t"] / best[(g, "TRUSTEnd")]["t"])
    losses = [r for r in ratios if r < LOSS]
    add("TrimaLossMin", fmt(min(losses)))
    add("TrimaLossMax", fmt(max(losses)))
    # Ladder ends (same blocks).
    suite_g = sorted((g for g in t40 if g not in ROADS), key=EDGES.get)
    fin = {g: t40_end(x, "trust") for g, x in t40.items()}
    add("ComposedSuiteGraphs", len(suite_g))
    win = []
    for f, name in (("steptc", "StepTC"), ("wetric", "WeTriC"), ("tricore", "TriCore")):
        w = [t40_end(t40[g], f) / fin[g] for g in suite_g]
        win += w
        add(f"ComposedTrima{name}Min", fmt(min(w)))
        add(f"ComposedTrima{name}Max", fmt(max(w), 1))
    add("ComposedTrimaWins", sum(w > GAIN for w in win))
    add("ComposedTrimaCells", len(win))
    comp = sorted(t40[g][("trust", "base")] / fin[g] for g in suite_g)
    add("ComposeMin", fmt(comp[0]))
    add("ComposeMax", fmt(comp[-1], 1))
    add("ComposeMed", fmt(st.median(comp), 1))
    gpu = R.gpu_rtx4080()
    for g, name in (("comlj", "Comlj"), ("orkut", "Orkut")):
        add(f"GpuOverTt{name}", fmt(fin[g] / gpu[(g, "trust")], 1))
    dend = [t40[g][("trust", "anchor")] / t40_trust(t40[g], "D-end") for g in ROADS]
    add("ScaffoldTrustRoadMin", fmt(min(dend)))
    add("ScaffoldTrustRoadMax", fmt(max(dend)))
    lad_eff = ladder_effects(effects, suite_times, lad, t40)
    sc = [e["speedup"] for e in lad_eff if e["principle"] == "scaffold" and not e["graph"].startswith("roadNet")]
    add("ScaffoldSuiteMin", fmt(min(sc)))
    add("ScaffoldSuiteMax", fmt(max(sc)))
    for key, tag in (("rowptr", "RowPtr"), ("trisc", "Trisc")):
        v = [e["speedup"] for e in lad_eff if e["principle"] == key]
        add(f"Rung{tag}Min", fmt(min(v)))
        add(f"Rung{tag}Max", fmt(max(v)))
    return lad_eff


# ---------------------------------------------------------------- tables

def table_abstime(times, add):
    """Count times (ms): end of the TRUST ladder, upload, fastest other TT family, fastest GPU family
    (RTX 4080) and GBBS (16 threads)."""
    best = best_times(times)
    cpu, up, gpu = R.cpu_times(), R.upload_times(), R.gpu_rtx4080()
    allg = {g for g, f in best if f == "TRUSTEnd"}
    roads = sorted((g for g in allg if g in ROADS), key=EDGES.get)
    graphs = sorted(allg - set(roads), key=EDGES.get) + roads
    short = {"StepTC": "S", "WeTriC": "W", "TriCore": "C", "TRUST": "T"}
    rows, rs = [], []
    for g in graphs:
        t = best[(g, "TRUSTEnd")]["t"]
        o = min((best[(g, f)] for f in PORTS if (g, f) in best), key=lambda x: x["t"])
        gp = [(v, FAM[f]) for (gg, f), v in gpu.items() if gg == g]
        gcell = f"{sig(1e3 * min(gp)[0])} ({short[min(gp)[1]]}{'' if len(gp) == 4 else '*'})"
        if g not in roads:
            rs.append(t / cpu[g])
        sep = "\\midrule\n" if g == roads[0] else ""
        rows.append(f"{sep}{LABELS[g]} & {sig(1e3 * t)} & {sig(1e3 * up[g])} & {sig(1e3 * o['t'])} "
                    f"({short[o['family']]}) & {gcell} & {sig(1e3 * cpu[g])} \\\\")
    add("CpuOverTtSuiteMin", fmt(1 / max(rs), 1))
    add("CpuOverTtSuiteMax", fmt(1 / min(rs), 1))
    lines = ["\\begin{tabular}{l r r r r r}", "\\toprule",
             "Graph & TRUST end & Upload & Other TT & GPU & CPU \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}"]
    (GEN / "abstime.tex").write_text("\n".join(lines) + "\n")


def table_families(times, lad, t40):
    """Per family and graph (ms): direct port and the end of the ladder (same blocks)."""
    base = {(t["graph"], t["family"]): t["t"] for t in times if t["variant"] == "base" and t["family"] in PORTS}
    graphs = sorted(lad["trust"], key=lambda g: (g in ROADS, EDGES[g]))
    rows = []
    for i, g in enumerate(graphs):
        x = t40.get(g)
        cells = []
        for f in ("steptc", "wetric", "tricore", "trust"):
            b = ((x or {}).get(("trust", "base")) or lad["trust"][g].get("L0")) if f == "trust" else base.get((g, FAM[f]))
            cells += [b, t40_end(x, f) if x else None]
        sep = "\\midrule\n" if g in ROADS and graphs[i - 1] not in ROADS else ""
        rows.append(f"{sep}{LABELS[g]} & " + " & ".join(sig(1e3 * v) if v else "--" for v in cells) + " \\\\")
    head = ["\\begin{tabular}{l rr rr rr rr}", "\\toprule",
            " & \\multicolumn{2}{c}{StepTC} & \\multicolumn{2}{c}{WeTriC} & \\multicolumn{2}{c}{TriCore} & \\multicolumn{2}{c}{TRUST} \\\\",
            "\\cmidrule(lr){2-3}\\cmidrule(lr){4-5}\\cmidrule(lr){6-7}\\cmidrule(lr){8-9}",
            "Graph" + " & Base & End" * 4 + " \\\\", "\\midrule"]
    (GEN / "families_times.tex").write_text("\n".join(head + rows + ["\\bottomrule", "\\end{tabular}"]) + "\n")


def table_trisc():
    """StepTC supply x TRISC factorial (ms): opt2, probes, C0, C1, R0, R1."""
    order = [("stanford", "Stanford"), ("comlj", "com-LJ"), ("orkut", "com-Orkut"), ("hollywood", "Hollywood")]
    x = R.trisc_factorial()
    rows = [f"{lab} & " + " & ".join(f"{1e3 * x[g][v]:.2f}" for v in ("opt2", "D3", "C0", "C1", "D0", "D1")) + " \\\\"
            for g, lab in order]
    (GEN / "trisc.tex").write_text("Graph & opt2 & probes & C0 & C1 & R0 & R1 \\\\\n" + "\n".join(rows) + "\n")


# ---------------------------------------------------------------- GPU ranking (numbers-gpu.tex, ranking.tex)

def kendall(d, i, j):
    c = dc = 0
    for a, b in combinations(d, 2):
        s = (d[a][i] - d[b][i]) * (d[a][j] - d[b][j])
        c, dc = c + (s > 0), dc + (s < 0)
    return (c - dc) / (c + dc)


def numbers_gpu(times, t40, suite_times, add):
    best = best_times(times)
    tt = {}
    for (g, f), t in best.items():
        f = "TRUST" if f == "TRUSTEnd" else f
        tt[(g, f)] = min(tt.get((g, f), t["t"]), t["t"])
    for g, x in t40.items():
        for (f, _), v in x.items():
            if f == "trust" and v:
                tt[(g, "TRUST")] = min(tt.get((g, "TRUST"), v), v)
    g4, g6 = R.gpu_rtx4080(), R.gpu_gtx1660()
    full = {}
    for g in R.GRAPHS:
        d = {f: (g4[(g, f)], tt[(g, NAME[f])]) for f in NAME if (g, f) in g4 and (g, NAME[f]) in tt}
        if len(d) == 4:
            full[g] = d
    gbest = {g: min(d, key=lambda f: d[f][0]) for g, d in full.items()}
    tbest = {g: min(d, key=lambda f: d[f][1]) for g, d in full.items()}
    taus = [kendall(d, 0, 1) for d in full.values()]
    add("GpuRankGraphs", len(full))
    add("GpuBestWetricN", sum(v == "wetric" for v in gbest.values()))
    add("TtBestTrustN", sum(v == "trust" for v in tbest.values()))
    add("GpuRankTauMed", f"{st.median(taus):.2f}")
    add("GpuRankTauMin", f"{min(taus):.2f}")
    add("GpuRankTauMax", f"{max(taus):.2f}")
    for f, n in NAME.items():
        add(f"TtOverGpu{n}", f"{st.median(d[f][1] / d[f][0] for d in full.values()):.0f}")
    # Direct ports: StepTC/WeTriC/TriCore base and TRUST B0 of the suite campaigns.
    base = {(t["graph"], t["family"]): t["t"] for t in suite_times if t["variant"] in ("base", "B0")}
    bsame, n = 0, 0
    for g, d in full.items():
        if all((g, NAME[f]) in base for f in d):
            n += 1
            bsame += gbest[g] == min(d, key=lambda f: base[(g, NAME[f])])
    add("GpuBaseRankGraphs", n)
    add("GpuBaseRankSameBest", bsame)
    cell = defaultdict(list)
    for r in R.gpu_metrics():
        cell[(r["family"], r["graph"])].append(r)
    want = {"LtwoHit": ["WeTriC"], "SecPerReq": ["TriCore", "WeTriC", "StepTC"], "WarpEff": ["TRUST", "WeTriC"]}
    for key, short in (("l2_sector_hit_pct", "LtwoHit"), ("global_load_sectors_per_request", "SecPerReq"),
                       ("warp_execution_efficiency_pct", "WarpEff")):
        for f, n in NAME.items():
            if n in want[short]:
                vals = [st.median(float(x[key]) for x in rs) for (ff, _), rs in cell.items() if ff == f]
                add(f"Gpu{short}{n}", f"{st.median(vals):.1f}")
    # Second GPU and the ranking table.
    fams = ("steptc", "wetric", "tricore", "trust")
    rows3 = {g: {f: (g4[(g, f)], g6[(g, f)], tt[(g, NAME[f])]) for f in fams}
             for g in {g for g, _ in g6} if all((g, f) in g6 for f in fams)}
    suite_g = [g for g in rows3 if g not in ROADS]
    bst = lambda g, i: min(rows3[g], key=lambda f: rows3[g][f][i])
    add("GpuTwoSameBest", sum(bst(g, 0) == bst(g, 1) for g in suite_g))
    add("GpuTwoTauMed", f"{st.median(kendall(rows3[g], 0, 1) for g in suite_g):.2f}")
    add("GpuTwoGraphs", len(suite_g))
    add("GpuMetricCells", sum(len(v) for v in cell.values()))
    order = sorted(suite_g, key=lambda g: g4[(g, "trust")]) + sorted((g for g in rows3 if g in ROADS),
                                                                     key=lambda g: g4[(g, "trust")])
    lines = ["\\begin{tabular}{l rrr rrr rrr rrr}", "\\toprule",
             " & " + " & ".join(f"\\multicolumn{{3}}{{c}}{{{NAME[f]}}}" for f in fams) + " \\\\",
             "".join(f"\\cmidrule(lr){{{2 + 3 * k}-{4 + 3 * k}}}" for k in range(4)),
             "Graph" + " & 4080 & 1660 & \\TT{}" * 4 + " \\\\", "\\midrule"]
    for g in order:
        if g == next(x for x in order if x in ROADS):
            lines.append("\\midrule")
        cells = []
        for f in fams:
            for i in range(3):
                v = sig(1e3 * rows3[g][f][i])
                cells.append(f"\\textbf{{{v}}}" if bst(g, i) == f else v)
        lines.append(f"{LABELS[g]} & " + " & ".join(cells) + " \\\\")
    (GEN / "ranking.tex").write_text("\n".join(lines + ["\\bottomrule", "\\end{tabular}"]) + "\n")


# ---------------------------------------------------------------- figures

def style_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
        ax.spines[s].set_linewidth(0.6)
    ax.tick_params(colors=MUTED, width=0.6, labelcolor=INK)


def log_ticks(ax, axis, ticks):
    (ax.set_xticks if axis == "x" else ax.set_yticks)(ticks)
    (ax.set_xticklabels if axis == "x" else ax.set_yticklabels)([f"{t:g}" for t in ticks])
    (ax.xaxis if axis == "x" else ax.yaxis).set_minor_locator(matplotlib.ticker.NullLocator())


def fig_distribution(effects, out):
    """Figure 1: effect of each rung of the four ladders."""
    plt.rcParams.update({"font.size": 7, "font.family": "sans-serif"})
    fig, ax = plt.subplots(figsize=(7.0, 3.5))
    ax.axvspan(LOSS, GAIN, color=GRID, alpha=0.6, lw=0, zorder=0)
    ax.axvline(1.0, color=MUTED, lw=0.6, zorder=1)
    all_rows = []
    for i, (p, _) in enumerate(ROWS):
        y0 = len(ROWS) - 1 - i
        labeled, row_losses = set(), []
        ax.axhline(y0, color=GRID, lw=0.5, zorder=0)
        fams = [f for f in FAMILY_STYLE if any(e["principle"] == p and e["family"] == f for e in effects)]
        for j, fam in enumerate(fams):
            off = (j - (len(fams) - 1) / 2) * 0.22
            color, marker = FAMILY_STYLE[fam]
            es = [e for e in effects if e["principle"] == p and e["family"] == fam]
            ax.scatter([e["speedup"] for e in es], [y0 + off] * len(es), s=16, marker=marker,
                       facecolor=color, edgecolor="white", linewidth=0.5, zorder=3)
            losses = sorted((e for e in es if e["speedup"] < 0.90), key=lambda e: e["speedup"])
            roads = [e for e in losses if e["graph"] in ROADS]
            losses = [] if p == "scaffold" else [e for e in losses if e["graph"] not in ROADS]
            if roads:
                losses.append(dict(roads[0], label="roads"))
                losses.sort(key=lambda e: e["speedup"])
            losses = [e for e in losses if e["label"] not in labeled]
            labeled.update(e["label"] for e in losses)
            row_losses += [(e, y0 + off) for e in losses]
        all_rows.append(row_losses)
    for row in all_rows:
        row.sort(key=lambda t: t[0]["speedup"])
        prev, flip = None, 1
        for e, y in row:
            close = prev is not None and e["speedup"] / prev < 1.15
            if close:
                flip = -flip
            ax.annotate(e["label"], (e["speedup"], y), xytext=(0, 6 * flip) if close else (-5, 0),
                        textcoords="offset points", ha="center" if close else "right",
                        va=("bottom" if flip > 0 else "top") if close else "center", fontsize=5.5, color=MUTED)
            prev = e["speedup"]
    ax.set_xscale("log")
    log_ticks(ax, "x", [0.3, 0.5, 0.7, 1.0, 1.5, 2.0])
    ax.set_xlim(0.30, 2.75)
    ax.set_yticks(range(len(ROWS)))
    ax.set_yticklabels([lbl for _, lbl in reversed(ROWS)])
    ax.set_ylim(-0.6, len(ROWS) - 0.4)
    ax.set_xlabel("Speedup of the rung over the rung before it (log scale)")
    style_axes(ax)
    ax.tick_params(axis="y", length=0)
    handles = [plt.Line2D([], [], ls="", marker=m, markersize=5, markerfacecolor=c, markeredgecolor="white",
                          label=f) for f, (c, m) in FAMILY_STYLE.items()]
    handles.append(matplotlib.patches.Patch(color=GRID, alpha=0.6, label="neutral (0.97-1.03)"))
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False, fontsize=6,
              ncol=6, handletextpad=0.3, columnspacing=1.0)
    fig.tight_layout(pad=0.2)
    fig.savefig(out)
    plt.close(fig)


def fig_supply(points, out):
    """Figure 3: speedup of range supply against the request ratio."""
    plt.rcParams.update({"font.size": 7, "font.family": "sans-serif"})
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    ax.axhspan(LOSS, GAIN, color=GRID, alpha=0.6, lw=0, zorder=0)
    ax.axhline(1.0, color=MUTED, lw=0.6, zorder=1)
    for r in points:
        color, marker = FAMILY_STYLE[FAM[r["family"]]]
        ringed = r["road"] or r["graph"] in ("friendster", "webcc")
        ax.scatter([r["ratio"]], [r["speedup"]], s=18, marker=marker, facecolor=color,
                   edgecolor=INK if ringed else "white", linewidth=0.9 if ringed else 0.5, zorder=3)
        if r["speedup"] < LOSS and not r["road"]:
            ax.annotate(LABELS[r["graph"]], (r["ratio"], r["speedup"]), xytext=(0, -6), textcoords="offset points",
                        ha="center", va="top", fontsize=5.5, color=MUTED)
    ax.annotate("road networks", (5.5, 0.47), fontsize=5.5, color=MUTED, ha="center", va="top")
    ax.set_xscale("log")
    ax.set_yscale("log")
    log_ticks(ax, "x", [0.7, 1, 2, 3, 4, 6])
    log_ticks(ax, "y", [0.4, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5])
    ax.set_xlim(0.6, 6.6)
    ax.set_ylim(0.37, 2.8)
    ax.set_xlabel("Read requests, range supply / page cache (log)")
    ax.set_ylabel("Speedup of range supply (log)")
    style_axes(ax)
    handles = [plt.Line2D([], [], ls="", marker=m, markersize=5, markerfacecolor=c, markeredgecolor="white",
                          label=f) for f, (c, m) in FAMILY_STYLE.items() if f in PORTS]
    handles += [plt.Line2D([], [], ls="", marker="o", markersize=5, markerfacecolor=MUTED,
                           markeredgecolor=INK, label="Friendster, WebCC, roads")]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False, fontsize=5.5,
              ncol=3, handletextpad=0.3, columnspacing=0.8)
    fig.tight_layout(pad=0.2)
    fig.savefig(out)
    plt.close(fig)


def fig_cumulative(times, lad, t40, out):
    """Figure 4: cumulative speedup over each family's direct port along its ladder."""
    T = {(t["graph"], t["family"], t["variant"]): t["t"] for t in times}
    seqs = {"TRUST": (["Base", "+prune", "+OA", "+range", "+probes", "+scaffold", "+T", "+TRISC", "+ctx"],
                      {g: [x.get(k) for k in ("L0", "L1", "L2", "L3", "L4")] + [t40_trust(t40[g], r) for r in T40_RUNGS]
                       for g, x in lad["trust"].items() if g in t40})}
    spec = {"StepTC": ("steptc", ["D1-direct", "D2-oa", "D3-oa-w4"], ["+range", "+OA", "+probes"], True),
            "WeTriC": ("wetric", ["D1-direct", "D5-bl4"], ["+range", "+lockstep"], False),
            "TriCore": ("tricore", ["D1-direct"], ["+range"], False)}
    for fam, (f, drungs, dnames, ctx) in spec.items():
        names = ["Base"] + dnames + ["+scaffold", "+T", "+TRISC"] + (["+ctx"] if ctx else [])
        rows = {}
        for g, x in lad["other"][f].items():
            def mn(k):
                vs = [x[m].get(k) for m in T40_MODES if x[m].get(k)]
                return min(vs) if vs else None
            rows[g] = ([T.get((g, fam, "base"))] + [T.get((g, fam, v)) for v in drungs]
                       + [mn("D-end"), mn("plus-T"), mn("end")] + ([mn("plus-context")] if ctx else []))
        seqs[fam] = (names, rows)
    plt.rcParams.update({"font.size": 6, "font.family": "sans-serif"})
    fig, axs = plt.subplots(2, 2, figsize=(3.4, 3.7), sharey=True)
    cmap = plt.get_cmap("viridis")
    order = sorted(EDGES, key=EDGES.get)
    for ax, fam in zip(axs.flat, ["TRUST", "StepTC", "WeTriC", "TriCore"]):
        names, rows = seqs[fam]
        for g, row in rows.items():
            if not row[0]:
                continue
            pts = [(i, row[0] / t) for i, t in enumerate(row) if t]
            road = g in ROADS
            ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", ms=1.6, lw=0.7,
                    color=MUTED if road else cmap(order.index(g) / len(order)), ls="--" if road else "-")
        ax.axhline(1, color=INK, lw=0.5)
        ax.set_yscale("log")
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=50, ha="right", fontsize=5)
        ax.set_title(fam, fontsize=6.5, pad=2)
        ax.grid(axis="y", color=GRID, lw=0.4)
        style_axes(ax)
    axs[0][0].set_yticks([0.25, 0.5, 1, 2, 4, 8])
    axs[0][0].set_yticklabels(["0.25", "0.5", "1", "2", "4", "8"])
    axs[0][0].set_ylim(0.25, 14)
    fig.supylabel("Cumulative speedup over the baseline port (log)", fontsize=6)
    fig.tight_layout(pad=0.2, h_pad=0.4, w_pad=0.3)
    fig.savefig(out)
    plt.close(fig)


def spearman(x, y):
    def rank(v):
        order = sorted(range(len(v)), key=v.__getitem__)
        r, i = [0.0] * len(v), 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    a, b = rank(x), rank(y)
    ma, mb = st.fmean(a), st.fmean(b)
    num = sum((p - ma) * (q - mb) for p, q in zip(a, b))
    return num / math.sqrt(sum((p - ma) ** 2 for p in a) * sum((q - mb) ** 2 for q in b))


def main():
    GEN.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    effects, suite_times, spreads = suite()
    lad, t40 = R.ladders(), R.ladder_ends()
    times = all_times(suite_times, lad, t40)
    lines = []
    add = lambda n, v: lines.append(f"\\newcommand{{\\{n}}}{{{v}}}")
    lad_eff = numbers_suite(effects, times, spreads, lad, t40, suite_times, add)
    table_abstime(times, add)
    table_families(times, lad, t40)
    table_trisc()
    (GEN / "numbers-suite.tex").write_text("\n".join(lines) + "\n")
    lines.clear()
    numbers_gpu(times, t40, suite_times, add)
    (GEN / "numbers-gpu.tex").write_text("\n".join(lines) + "\n")
    pts = R.supply_points()
    suite_pts = [p for p in pts if not p["road"]]
    print("range supply: Spearman rho, request ratio (suite)",
          round(spearman([p["ratio"] for p in suite_pts], [p["speedup"] for p in suite_pts]), 2),
          "| byte ratio (suite)", round(spearman([p["byte_ratio"] for p in suite_pts], [p["speedup"] for p in suite_pts]), 2),
          "| request ratio with roads", round(spearman([p["ratio"] for p in pts], [p["speedup"] for p in pts]), 2))
    fig_distribution(lad_eff, FIG / "principle_dist.pdf")
    fig_supply(pts, FIG / "supply_condition.pdf")
    fig_cumulative(times, lad, t40, FIG / "cumulative_ladders.pdf")
    print(f"wrote {GEN} and {FIG}")


if __name__ == "__main__":
    main()
