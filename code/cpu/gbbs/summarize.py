#!/usr/bin/env python3
"""Summarize campaign cells.jsonl into results.json (median of block medians, block spread).

Usage: python3 -I summarize.py cells.jsonl graphs.json prepare.json environment.json results.json
"""
import json, statistics, sys

METRICS = ["count_time", "running_time", "build_graph_time", "rank_time"]


def main():
    cells = [json.loads(l) for l in open(sys.argv[1])]
    graphs = json.load(open(sys.argv[2]))["graphs"]
    prep = json.load(open(sys.argv[3]))
    env = json.load(open(sys.argv[4]))
    out = {"environment": env, "protocol": {
        "threads": [16, 8], "blocks": 3, "per_cell": "1 warm-up + 3 measured rounds in one process (graph loaded once, untimed)",
        "order": "graph order shuffled per block, random.Random(20261027 + 1000*T + block)",
        "statistic": "median over blocks of the per-block median of 3 measured rounds; spread = (max-min)/median of the 3 block medians",
        "primary_metric": "count_time", "units": "seconds"}, "graphs": []}
    for g in graphs:
        name = g["name"]
        row = {"graph": name, "label": g["label"], "n": g["n"], "m": g["m"],
               "triangles_expected": g["triangles"], "input_sha256": prep[name]["input_sha256"],
               "input_sha256_verified": prep[name]["input_sha256_verified"],
               "repo_dag_total_work": prep[name]["repo_dag_total_work"],
               "max_forward_degree": prep[name]["max_forward_degree"]}
        for T in (16, 8):
            cs = sorted([c for c in cells if c["graph"] == name and c["threads"] == T], key=lambda c: c["block"])
            if len(cs) != 3:
                row[f"T{T}"] = None
                continue
            r = {"blocks": [c["block"] for c in cs]}
            for mt in METRICS:
                bm = [statistics.median(x[mt] for x in c["measured"]) for c in cs]
                med = statistics.median(bm)
                r[mt] = {"median_s": med, "block_medians_s": bm,
                         "block_spread_pct": 100 * (max(bm) - min(bm)) / med,
                         "runs_s": [[x[mt] for x in c["measured"]] for c in cs]}
            tri = {x["triangles"] for c in cs for x in [c["warmup"], *c["measured"]]}
            assert tri == {g["triangles"]}, (name, T, tri)
            r["triangles_all_runs"] = g["triangles"]
            r["gbbs_total_work"] = sorted({x["gbbs_total_work"] for c in cs for x in c["measured"]})
            r["load"] = [{"block": c["block"], "before": c["load_before"], "after": c["load_after"]} for c in cs]
            r["max_other_users_cpu_pct"] = max(max(c["load_before"]["other_users_cpu_pct"], c["load_after"]["other_users_cpu_pct"]) for c in cs)
            r["warmup_count_time_s"] = [c["warmup"]["count_time"] for c in cs]
            r["processes_per_cell"] = cs[0]["processes"]
            r["thermal"] = [{"block": c["block"], "per_process": [
                {k: th.get(k) for k in ("tctl_start_c", "cool_wait_s", "tctl_max_c", "tctl_mean_c", "mhz_mean", "mhz_min")}
                for th in c["thermal_per_process"]]} for c in cs]
            r["max_other_users_cpu_pct"] = max(r["max_other_users_cpu_pct"], *(
                th["load_before"]["other_users_cpu_pct"] for c in cs for th in c["thermal_per_process"]))
            row[f"T{T}"] = r
        out["graphs"].append(row)
    json.dump(out, open(sys.argv[5], "w"), indent=1)
    for row in out["graphs"]:
        f = lambda T, k="count_time": (f"{row[f'T{T}'][k]['median_s']:.6f} ({row[f'T{T}'][k]['block_spread_pct']:.1f}%)" if row[f"T{T}"] else "-")
        print(f"{row['label']:12s} 16T count {f(16)}  total {f(16,'running_time')}  8T count {f(8)}  total {f(8,'running_time')}")


if __name__ == "__main__":
    main()
