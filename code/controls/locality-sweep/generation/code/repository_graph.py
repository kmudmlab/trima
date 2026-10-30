# SPDX-FileCopyrightText: © 2026 Ha-Myung Park
# SPDX-License-Identifier: Apache-2.0

"""Host-side graph preparation, matching ref/tri.c exactly.

The device kernels consume a flat uint32 image of a CSR, so everything the
host has to decide -- the total order, the orientation, the sort -- is settled
here and the kernel only walks arrays.

Order is PTE Definition 2: u < v iff deg(u) < deg(v), ties by id.  Orienting
every edge low->high bounds d+(u) by sqrt(2|E|), which is what keeps the work
at O(|E|^1.5), and it is also what makes the counting loop emit each triangle
exactly once without any deduplication pass.
"""
import numpy as np


def load_edges(path):
    """Undirected simple edge list -> (eu, ev, n), self loops dropped."""
    with open(path, "rb") as f:
        raw = f.read()
    # SNAP files open with '#' comment lines; strip them before parsing.
    if raw.startswith(b"#"):
        lines = raw.split(b"\n")
        keep = next(i for i, ln in enumerate(lines) if not ln.startswith(b"#"))
        raw = b"\n".join(lines[keep:])
    vals = np.array(raw.split(), dtype=np.int64)
    eu, ev = vals[0::2], vals[1::2]
    keep = eu != ev
    eu, ev = eu[keep], ev[keep]
    n = int(max(eu.max(), ev.max())) + 1
    return eu, ev, n


def build_csr(eu, ev, n):
    """Degree-ordered, low->high oriented, sorted, duplicate-free CSR.

    Returns (row_ptr, col_idx) as uint32, both over original vertex ids.
    """
    deg = np.bincount(eu, minlength=n) + np.bincount(ev, minlength=n)

    # u precedes v iff (deg(u), u) < (deg(v), v)
    du, dv = deg[eu], deg[ev]
    u_first = (du < dv) | ((du == dv) & (eu < ev))
    lo = np.where(u_first, eu, ev)
    hi = np.where(u_first, ev, eu)

    order = np.lexsort((hi, lo))
    lo, hi = lo[order], hi[order]

    # drop duplicate (lo, hi) pairs -- a directed input contributes each edge
    # twice and both copies land on the same oriented pair
    keep = np.empty(lo.size, dtype=bool)
    keep[0] = True
    np.not_equal(lo[1:], lo[:-1], out=keep[1:])
    np.logical_or(keep[1:], hi[1:] != hi[:-1], out=keep[1:])
    lo, hi = lo[keep], hi[keep]

    dout = np.bincount(lo, minlength=n)
    row_ptr = np.zeros(n + 1, dtype=np.uint32)
    np.cumsum(dout, out=row_ptr[1:])
    return row_ptr, hi.astype(np.uint32)


PAGE_WORDS = 1024


def pack(row_ptr, col_idx):
    """Flat uint32 image the kernels read:

        [0]        n
        [1]        m
        [2 .. n+2] row_ptr
        [n+3 ..]   col_idx

    Padded to a whole number of 4096-byte pages.
    """
    n = row_ptr.size - 1
    m = col_idx.size
    words = 2 + (n + 1) + m
    pages = (words + PAGE_WORDS - 1) // PAGE_WORDS
    buf = np.zeros(pages * PAGE_WORDS, dtype=np.uint32)
    buf[0] = n
    buf[1] = m
    buf[2:3 + n] = row_ptr
    buf[3 + n:3 + n + m] = col_idx
    return buf.reshape(pages, PAGE_WORDS)


def merge_comparisons(row_ptr, col_idx):
    """Iterations the device merge loop will run, for a rate denominator.

    Mirrors the kernel: for every oriented edge (u,v), merge adj[u] from the
    position of v onward against adj[v].  Pure numpy is too awkward here, so
    this walks it directly; it is only used on small graphs.
    """
    rp = row_ptr.astype(np.int64)
    ci = col_idx.astype(np.int64)
    total = 0
    for u in range(rp.size - 1):
        us, ue = rp[u], rp[u + 1]
        for p in range(us, ue):
            v = ci[p]
            i, j, je = us, rp[v], rp[v + 1]
            while i < ue and j < je:
                total += 1
                x, y = ci[i], ci[j]
                if x == y:
                    i += 1
                    j += 1
                elif x < y:
                    i += 1
                else:
                    j += 1
    return total
