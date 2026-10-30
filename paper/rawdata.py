"""Readers for the raw measurements in results/.

Every time is the median of the three block medians of a cell (each block median is the median
of three measured runs after one warm-up run). Request counts come from the separate profiling
runs of the same code.
"""
import json
import math
import re
import statistics
from pathlib import Path

RES = Path(__file__).resolve().parents[1] / "results"

GRAPHS = ["fb", "notredame", "stanford", "google", "berkstan", "wikitalk", "skitter",
          "patents", "comlj", "soclj", "hollywood", "orkut", "friendster", "webcc"]
ROADS = ["roadNet-PA", "roadNet-TX", "roadNet-CA"]
LABELS = {"fb": "Facebook", "notredame": "NotreDame", "stanford": "Stanford", "google": "Google",
          "berkstan": "BerkStan", "wikitalk": "WikiTalk", "skitter": "Skitter", "patents": "Patents",
          "comlj": "com-LJ", "soclj": "soc-LJ", "hollywood": "Hollywood", "orkut": "com-Orkut",
          "friendster": "Friendster", "webcc": "WebCC",
          "roadNet-PA": "roadNet-PA", "roadNet-TX": "roadNet-TX", "roadNet-CA": "roadNet-CA"}
EDGES = {"fb": 88234, "notredame": 1090108, "stanford": 1992636, "google": 4322051, "berkstan": 6649470,
         "wikitalk": 4659565, "skitter": 11095298, "patents": 16518947, "comlj": 34681189,
         "soclj": 42851237, "hollywood": 56375711, "orkut": 117185083, "friendster": 1806067135,
         "webcc": 1940007864, "roadNet-PA": 1541898, "roadNet-TX": 1921660, "roadNet-CA": 2766607}
FAM = {"steptc": "StepTC", "wetric": "WeTriC", "tricore": "TriCore", "trust": "TRUST"}
DONE = ("complete", "stop_supply_counterexample", "complete_with_time_limits")


def load(path):
    return json.loads(Path(path).read_text())


def median3(xs):
    return statistics.median(xs) if len(xs) == 3 else None


# ---------------------------------------------------------------- suite campaigns (suite-v1)

def suite_campaign(graph, kind):
    """The one finished direct (StepTC, WeTriC, TriCore) or source (TRUST) campaign of a graph."""
    done = [d for d in sorted((RES / "suite-v1").glob(f"{graph}-{kind}-*"))
            if (d / "status.json").exists() and load(d / "status.json").get("status") in DONE]
    return done[0] if len(done) == 1 else None


def suite_profile(graph, name):
    """profile.json of a suite profiling cell; WebCC's StepTC profiles sit in its first campaign."""
    for d in sorted((RES / "suite-v1").glob(f"{graph}-direct-*")):
        p = d / name / "profile.json"
        if p.exists():
            return load(p)
    return None


def block_medians_status(status, family, variant):
    """{block: median} of the timing cells of a variant in a campaign status, or None on a failed cell."""
    out = {}
    for r in status["records"]:
        if r.get("phase") != "timing" or r.get("variant") != variant:
            continue
        if family is not None and r.get("family") != family:
            continue
        s = r.get("summary", r)
        if r.get("returncode", 0) != 0 or s.get("status") != "pass":
            return None
        out[r.get("block")] = s["median_s"]
    return out


# ---------------------------------------------------------------- range supply: request ratio

def request_ratio(base, d1):
    """Range requests over the page cache's page reads (row, column and auxiliary arrays)."""
    cb, cd = base["counters"], d1["counters"]
    assert cb["candidates"] == cd["candidates"], "candidate totals differ"
    q_base = cb["row_pages"] + cb["col_pages"] + cb["aux_pages"]
    q_d1 = sum(cd["range_requests_row_col_aux"])
    b_base = base["page_bytes"] * q_base
    b_d1 = sum(cd["range_bytes_row_col_aux"])
    return q_d1 / q_base, b_d1 / b_base, q_d1, b_d1


def supply_points():
    """One row per family and graph: request ratio, byte ratio and speedup of range supply."""
    rows = []
    for g in GRAPHS:
        cdir = suite_campaign(g, "direct")
        st = load(cdir / "status.json")
        for f in ("steptc", "wetric", "tricore"):
            base, d1 = suite_profile(g, f"profile-{f}-base"), suite_profile(g, f"profile-{f}-D1-direct")
            q, b, qd, bd = request_ratio(base, d1)
            tb = median3(list(block_medians_status(st, f, "base").values()))
            td = median3(list(block_medians_status(st, f, "D1-direct").values()))
            rows.append({"graph": g, "family": f, "ratio": q, "byte_ratio": b, "speedup": tb / td,
                         "range_requests": qd, "range_bytes": bd, "road": False})
    st = load(RES / "roads-v1" / "status.json")
    for g in ROADS:
        for f in ("steptc", "wetric", "tricore"):
            base = load(RES / "roads-v1" / f"profile-{g}-{f}-base" / "profile.json")
            d1 = load(RES / "roads-v1" / f"profile-{g}-{f}-D1-direct" / "profile.json")
            q, b, qd, bd = request_ratio(base, d1)
            t = road_times()
            rows.append({"graph": g, "family": f, "ratio": q, "byte_ratio": b,
                         "speedup": t[(g, f, "base")] / t[(g, f, "D1-direct")],
                         "range_requests": qd, "range_bytes": bd, "road": True})
    return rows


def road_times():
    """Direct ports and their D rungs on the road networks: {(graph, family, variant): s}."""
    med = {}
    for r in load(RES / "roads-v1" / "status.json")["records"]:
        if r.get("phase") == "timing" and r.get("status") == "pass":
            med.setdefault((r["graph"], r["family"], r["variant"]), []).append(r["median_s"])
    return {k: statistics.median(v) for k, v in med.items() if len(v) == 3}


# ---------------------------------------------------------------- ladders (ladders-v1, ladder-ends-v1)

def _cells(root, pattern):
    """{key: [median per block]} for cell directories block<b>-<name> under root matching pattern."""
    med = {}
    for d in root.glob("block*"):
        m = re.match(pattern, d.name)
        if m and (d / "summary.json").exists():
            s = load(d / "summary.json")
            if s.get("status", "pass") == "pass":
                med.setdefault(m.groups()[1:], []).append(s["median_s"])
    return med


GRAPH_RE = r"(roadNet-..|[^-]+)"


def ladders():
    """TRUST L0-L7 and the other ladders' rungs from the ladder campaign.

    Returns {"trust": {graph: {L: s}}, "other": {family: {graph: {mode: {rung: s}}}}} where the
    other ladders' rungs are D-end (scaffolding), plus-T, end (TRISC consumers) and plus-context,
    and "anchor" is the family's earlier port timed in the same blocks."""
    cells = {}
    for root in (RES / "ladders-v1", RES / "ladders-v1-block0"):
        for k, v in _cells(root, rf"block(\d)-([AB])-{GRAPH_RE}-(.+)$").items():
            cells.setdefault(k, []).extend(v)
    trust, other = {}, {}
    for (kind, g, rest), xs in cells.items():
        t = median3(xs)
        if kind == "A":
            trust.setdefault(g, {})[rest] = t
            continue
        m = re.match(r"(steptc|wetric|tricore)-(?:(anchor)|(range|cache)(?:-(D-end|plus-T|plus-context))?)$", rest)
        if not m:
            continue
        f, anchor, mode, rung = m.groups()
        x = other.setdefault(f, {}).setdefault(g, {"range": {}, "cache": {}})
        if anchor:
            x["range"]["anchor"] = x["cache"]["anchor"] = t
        else:
            x[mode][rung or "end"] = t
    return {"trust": trust, "other": other}


def ladder_ends():
    """Same-block campaign of TRUST's last rungs (both supply modes), TRUST Base and every ladder's end
    and anchor: {graph: {(family, variant): s}}."""
    out = {}
    for (g, f, v), xs in _cells(RES / "ladder-ends-v1",
                                rf"block(\d)-{GRAPH_RE}-(steptc|wetric|tricore|trust)-(.+)$").items():
        if median3(xs):
            out.setdefault(g, {})[(f, v)] = median3(xs)
    return out


# ---------------------------------------------------------------- other timings

def hash_port_times():
    """Ports with the multiply-shift hash and with a two-round mix: [(graph, family, variant, s)]."""
    out = []
    for f in [*(RES / "hash-two-round-mix-v1").glob("*/comparison.json"),
              *(RES / "hash-multiply-shift-v1").glob("*/*/comparison.json")]:
        for k, v in load(f)["seconds"].items():
            fam, var = k.split("-", 1)
            out.append((f.parent.name, FAM[fam], var, v))
    return out


def trisc_factorial():
    """StepTC supply x TRISC factorial (Table V): {graph: {opt2, D3, C0, C1, D0, D1: s}}."""
    out = {}
    for d in ("stanford-v2", "comlj-v1", "orkut-trisc-continue-v1", "hollywood-trisc-continue-v1"):
        c = load(RES / "trisc-factorial-v1" / d / "comparison.json")
        out[c["graph"]] = c["seconds"]
    return out


def upload_times():
    med = {}
    for d in (RES / "upload-v1").glob("block*-*"):
        if (d / "summary.json").exists():
            med.setdefault(d.name.split("-", 1)[1], []).append(load(d / "summary.json")["median_s"])
    return {g: median3(v) for g, v in med.items()}


def cpu_times():
    return {r["graph"]: r["T16"]["count_time"]["median_s"] for r in load(RES / "cpu-gbbs-v1" / "results.json")["graphs"]}


def gpu_block_medians(root, family=None):
    """{(graph, family): s} from GPU cells block<b>-<graph>-<family>[-attempt<n>]; the last passing
    attempt of each block counts."""
    blocks = {}
    for d in sorted(root.glob("block*")):
        m = re.match(rf"block(\d)-{GRAPH_RE}-(steptc|wetric|tricore|trust)(?:-attempt(\d+))?$", d.name)
        if not m or not (d / "summary.json").exists():
            continue
        s = load(d / "summary.json")
        if s.get("status", "pass") != "pass":
            continue
        b, g, f, a = m.groups()
        prev = blocks.get((g, f, b))
        if prev is None or int(a or 0) >= prev[0]:
            blocks[(g, f, b)] = (int(a or 0), s["median_s"])
    med = {}
    for (g, f, b), (_, t) in blocks.items():
        med.setdefault((g, f), []).append(t)
    return {k: median3(v) for k, v in med.items() if median3(v)}


def gpu_rtx4080():
    t = gpu_block_medians(RES / "gpu-rtx4080-v1")
    t.update(gpu_block_medians(RES / "gpu-rtx4080-roads-v1" / "recovery-v1" / "attempts"))
    return t


def gpu_gtx1660():
    return gpu_block_medians(RES / "gpu-gtx1660-v1")


def gpu_metrics():
    import csv
    return list(csv.DictReader((RES / "gpu-rtx4080-metrics-v1" / "metrics-by-cell.csv").open()))


def log_ratio(a, b):
    return math.log(a / b)
