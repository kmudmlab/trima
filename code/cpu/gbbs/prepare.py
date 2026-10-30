#!/usr/bin/env python3
"""Verify device-input SHA256 and convert each forward CSR to GBBS symmetric binary.

Run on bear: python3 prepare.py graphs.json /data0/hmpark/cpu-baseline-v1/inputs/gbbs
Writes <out>/<name>.sym.bin and <out>/prepare.json. Stops on any mismatch.
"""
import hashlib, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()


def main():
    cfg = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    rec_path = os.path.join(out, "prepare.json")
    recs = json.load(open(rec_path)) if os.path.exists(rec_path) else {}
    for g in cfg["graphs"]:
        name = g["name"]
        dst = os.path.join(out, name + ".sym.bin")
        if name in recs and os.path.exists(dst):
            print("skip", name, flush=True)
            continue
        got = sha256(g["path"])
        if got != g["sha256"]:
            sys.exit(f"SHA256 MISMATCH {name}: {got} != {g['sha256']}")
        t0 = time.time()
        r = subprocess.run([os.path.join(HERE, "fwd2gbbs"), g["path"], dst],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"convert failed {name}: {r.stderr}")
        info = json.loads(r.stdout.strip().splitlines()[-1])
        if info["n"] != g["n"] or info["m_undirected"] != g["m"]:
            sys.exit(f"n/m mismatch {name}: {info} vs Table III n={g['n']} m={g['m']}")
        info.update(input_path=g["path"], input_sha256=got, input_sha256_verified=True,
                    gbbs_path=dst, gbbs_sha256=sha256(dst),
                    convert_s=round(time.time() - t0, 2))
        recs[name] = info
        json.dump(recs, open(rec_path, "w"), indent=1)
        print(name, json.dumps(info), flush=True)


if __name__ == "__main__":
    main()
