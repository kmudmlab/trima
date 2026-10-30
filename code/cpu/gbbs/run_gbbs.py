#!/usr/bin/env python3
"""GBBS exact triangle counting campaign on bear.

Protocol: for each thread count (16, then 8), 3 blocks; each block runs every
graph in an order shuffled with a fixed seed. Each (block, graph) cell is one
process `Triangle_main -s -b -rounds 4 <graph>`: the graph is loaded once
(untimed), round 1 is the warm-up, rounds 2-4 are measured. Every round's
triangle count must equal Table III, otherwise the campaign stops.

Before every cell the load of other users is sampled with `top`; if another
user's processes use CPU the cell waits and rechecks. Load is logged per cell.

Thermal gate (added after campaign-v1 was aborted): bear's CPU reaches Tctl 95 C
and throttles from ~4.0 GHz to ~2.5 GHz under minutes of sustained load. Before
every process the runner waits until Tctl <= TCTL_GATE. Graphs whose single
round lasts minutes (LONG_GRAPHS) run each round (warm-up and the 3 measured)
as its own process, each behind the gate; the others run as one process with
-rounds 4. Tctl and mean core MHz are sampled every 2 s during each process
and recorded.

Usage: python3 run_gbbs.py graphs.json prepare.json out_dir [--threads 16,8] [--only g1,g2]
"""
import argparse, json, os, random, re, subprocess, sys, threading, time

BIN = "/data0/hmpark/cpu-baseline-v1/gbbs/bazel-bin/benchmarks/TriangleCounting/ShunTangwongsan15/Triangle_main"
ME = "hmpark"
SEED = 20261027
BLOCKS = 3
ROUNDS = 4  # 1 warm-up + 3 measured
# One logical CPU per physical core for 8 threads (siblings are c and c+8).
CPUSET = {16: "0-15", 8: "0-7"}
OTHER_CPU_LIMIT = 10.0  # % summed over other users' processes (one core = 100)
WAIT_S = 60
TCTL_GATE = 65.0
LONG_GRAPHS = {"friendster", "webcc"}


def tctl():
    out = subprocess.run(["sensors"], capture_output=True, text=True).stdout
    m = re.search(r"Tctl:\s*\+([0-9.]+)", out)
    return float(m.group(1))


def mean_mhz():
    v = [float(l.split(":")[1]) for l in open("/proc/cpuinfo") if l.startswith("cpu MHz")]
    return sum(v) / len(v)


def wait_cool(log):
    t0 = time.time()
    while True:
        t = tctl()
        if t <= TCTL_GATE:
            return {"tctl_start_c": t, "cool_wait_s": round(time.time() - t0, 1)}
        time.sleep(10)


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop, self.s = threading.Event(), []

    def run(self):
        while not self.stop.is_set():
            try:
                self.s.append((tctl(), mean_mhz()))
            except Exception:
                pass
            self.stop.wait(2.0)

    def summary(self):
        self.stop.set()
        self.join()
        if not self.s:
            return {}
        t = [x[0] for x in self.s]
        f = [x[1] for x in self.s]
        return {"tctl_max_c": max(t), "tctl_mean_c": round(sum(t) / len(t), 1),
                "mhz_mean": round(sum(f) / len(f)), "mhz_min": round(min(f)), "samples": len(t)}


def run_proc(cmd, env, log):
    gate = wait_cool(log)
    gate["load_before"] = wait_quiet(log)
    smp = Sampler()
    smp.start()
    t0 = time.time()
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    th = smp.summary()
    th.update(gate)
    th["process_wall_s"] = round(time.time() - t0, 3)
    return r, th


def sample_load():
    up = open("/proc/loadavg").read().split()[:3]
    out = subprocess.run(["top", "-b", "-n", "2", "-d", "1", "-w", "250"],
                         capture_output=True, text=True).stdout
    frame = out.split("\ntop - ")[-1]  # second frame = 1 s interval
    lines = frame.splitlines()
    hdr = next(i for i, l in enumerate(lines) if l.strip().startswith("PID"))
    other, mine, offenders = 0.0, 0.0, []
    for l in lines[hdr + 1:]:
        f = l.split(None, 11)
        if len(f) < 12:
            continue
        user, cpu = f[1], float(f[8])
        if cpu == 0.0:
            continue
        if user == ME:
            mine += cpu
        else:
            other += cpu
            if cpu >= 2.0:
                offenders.append(f"{user}:{f[11][:40]}:{cpu}")
    return {"loadavg": up, "other_users_cpu_pct": round(other, 1),
            "own_cpu_pct": round(mine, 1), "other_top": offenders[:5],
            "time": time.strftime("%Y-%m-%dT%H:%M:%S")}


def wait_quiet(log):
    waited = 0
    while True:
        s = sample_load()
        if s["other_users_cpu_pct"] <= OTHER_CPU_LIMIT:
            s["waited_s"] = waited
            return s
        print(f"  busy: {s}", file=log, flush=True)
        time.sleep(WAIT_S)
        waited += WAIT_S


def parse(stdout):
    rounds, cur = [], None
    for line in stdout.splitlines():
        if line.startswith("### Application"):
            cur = {}
            rounds.append(cur)
        m = re.match(r"### (rank time|build graph time|count time|Running Time): ([0-9.eE+-]+)", line)
        if m:
            cur[m.group(1).replace(" ", "_").lower()] = float(m.group(2))
        m = re.match(r"### Num triangles = (\d+)", line)
        if m:
            cur["triangles"] = int(m.group(1))
        m = re.match(r"Total work = (\d+)", line)
        if m:
            cur["gbbs_total_work"] = int(m.group(1))
        m = re.match(r"### Threads: (\d+)", line)
        if m:
            cur["threads_reported"] = int(m.group(1))
    return rounds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graphs")
    ap.add_argument("prepare")
    ap.add_argument("out")
    ap.add_argument("--threads", default="16,8")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    cfg = json.load(open(a.graphs))["graphs"]
    prep = json.load(open(a.prepare))
    if a.only:
        keep = a.only.split(",")
        cfg = [g for g in cfg if g["name"] in keep]
    os.makedirs(a.out, exist_ok=True)
    res_path = os.path.join(a.out, "cells.jsonl")
    done = set()
    if os.path.exists(res_path):
        for l in open(res_path):
            r = json.loads(l)
            done.add((r["threads"], r["block"], r["graph"]))
    log = open(os.path.join(a.out, "campaign.log"), "a")
    for T in [int(t) for t in a.threads.split(",")]:
        for b in range(BLOCKS):
            order = [g["name"] for g in cfg]
            random.Random(SEED + 1000 * T + b).shuffle(order)
            print(f"T={T} block={b} order={order}", file=log, flush=True)
            for name in order:
                if (T, b, name) in done:
                    continue
                g = next(x for x in cfg if x["name"] == name)
                p = prep[name]
                assert p["input_sha256"] == g["sha256"]
                load = wait_quiet(log)
                env = dict(os.environ, PARLAY_NUM_THREADS=str(T))
                base = ["taskset", "-c", CPUSET[T], BIN, "-s", "-b"]
                if name in LONG_GRAPHS:
                    procs = [base + ["-rounds", "1", p["gbbs_path"]] for _ in range(ROUNDS)]
                else:
                    procs = [base + ["-rounds", str(ROUNDS), p["gbbs_path"]]]
                stdout, thermal = "", []
                for k, cmd in enumerate(procs):
                    r, th = run_proc(cmd, env, log)
                    raw = os.path.join(a.out, "raw", f"T{T}-b{b}-{name}-p{k}.txt")
                    os.makedirs(os.path.dirname(raw), exist_ok=True)
                    open(raw, "w").write(" ".join(cmd) + "\n" + r.stdout + "\n--- stderr ---\n" + r.stderr)
                    if r.returncode != 0:
                        sys.exit(f"FAILED {name} T={T} b={b} rc={r.returncode}")
                    stdout += r.stdout
                    thermal.append(th)
                rounds = parse(stdout)
                if len(rounds) != ROUNDS:
                    sys.exit(f"expected {ROUNDS} rounds, got {len(rounds)} for {name}")
                for i, rd in enumerate(rounds):
                    if rd.get("triangles") != g["triangles"]:
                        sys.exit(f"TRIANGLE MISMATCH {name} T={T} b={b} round={i}: {rd.get('triangles')} != {g['triangles']}")
                    if rd.get("threads_reported") != T:
                        sys.exit(f"thread mismatch {name}: {rd}")
                load_after = sample_load()
                rec = {"threads": T, "block": b, "graph": name, "cpuset": CPUSET[T],
                       "warmup": rounds[0], "measured": rounds[1:],
                       "processes": len(procs), "thermal_per_process": thermal,
                       "load_before": load, "load_after": load_after}
                with open(res_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
                ms = [x["count_time"] for x in rounds[1:]]
                print(f"T={T} b={b} {name} count={ms} total={[x['running_time'] for x in rounds[1:]]} "
                      f"other_cpu={load['other_users_cpu_pct']} la={load['loadavg']} "
                      f"thermal={[(x.get('tctl_start_c'), x.get('tctl_max_c'), x.get('mhz_mean')) for x in thermal]}", file=log, flush=True)
    print("DONE", file=log, flush=True)


if __name__ == "__main__":
    main()
