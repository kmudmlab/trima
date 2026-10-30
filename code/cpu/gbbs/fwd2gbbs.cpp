// Convert the repo's degree-ordered forward CSR into a GBBS symmetric binary
// adjacency graph (the format read by `Triangle_main -s -b`).
//
// Input  (repo format, little endian):
//   u32 n, u32 m, u32 rowptr[n+1], u32 col[m]
//   Each undirected edge stored once, from lower to higher ID (ID = degree rank).
// Output (GBBS binary, gbbs/graph_io.cc parse_unweighted_graph with -b):
//   i64 n, i64 M (= 2m directed edges), i64 total_bytes,
//   u64 offsets[n+1], u32 edges[M]
//   Neighbor lists sorted ascending (in-neighbors < v, then out-neighbors > v).
//
// Also prints a JSON line with checks and the statistic GBBS prints as
// "Total work" (sum over directed DAG edges (u,v) of outdeg(v)) computed on the
// repo's own orientation, so the DAG GBBS builds internally can be compared.
//
// Build: g++ -O3 -march=native -fopenmp -o fwd2gbbs fwd2gbbs.cpp
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <omp.h>

static void die(const char* msg) { fprintf(stderr, "ERROR: %s\n", msg); exit(2); }

int main(int argc, char** argv) {
  if (argc != 3) die("usage: fwd2gbbs in.csr out.gbbs.bin");
  FILE* f = fopen(argv[1], "rb");
  if (!f) die("open input");
  uint32_t hdr[2];
  if (fread(hdr, 4, 2, f) != 2) die("read header");
  const uint64_t n = hdr[0], m = hdr[1];
  std::vector<uint32_t> rp(n + 1);
  std::vector<uint32_t> col(m);
  if (fread(rp.data(), 4, n + 1, f) != n + 1) die("read rowptr");
  if (m && fread(col.data(), 4, m, f) != m) die("read col");
  if (fgetc(f) != EOF) die("trailing bytes in input");
  fclose(f);
  if (rp[0] != 0 || rp[n] != m) die("rowptr bounds");

  // Validate: forward, strictly increasing within a row, in range.
  uint64_t bad = 0, maxfwd = 0;
#pragma omp parallel for schedule(dynamic, 4096) reduction(+ : bad) reduction(max : maxfwd)
  for (uint64_t u = 0; u < n; u++) {
    if (rp[u] > rp[u + 1]) { bad++; continue; }
    uint64_t d = rp[u + 1] - rp[u];
    if (d > maxfwd) maxfwd = d;
    uint32_t prev = (uint32_t)u;
    for (uint64_t e = rp[u]; e < rp[u + 1]; e++) {
      uint32_t v = col[e];
      if (v >= n || v <= prev) bad++;
      prev = v;
    }
  }
  if (bad) { fprintf(stderr, "bad entries: %llu\n", (unsigned long long)bad); die("input not a sorted forward CSR"); }

  // Symmetric degrees.
  std::vector<uint64_t> deg(n, 0);
  for (uint64_t u = 0; u < n; u++) deg[u] += rp[u + 1] - rp[u];
  for (uint64_t e = 0; e < m; e++) deg[col[e]]++;
  std::vector<uint64_t> off(n + 1);
  off[0] = 0;
  for (uint64_t u = 0; u < n; u++) off[u + 1] = off[u] + deg[u];
  const uint64_t M = off[n];
  if (M != 2 * m) die("2m mismatch");

  std::vector<uint32_t> adj(M);
  // in-neighbors first: scanning u ascending appends u to each v's list in
  // ascending order; fill pointer starts at off[v].
  std::vector<uint64_t> pos(off.begin(), off.end() - 1);
  for (uint64_t u = 0; u < n; u++)
    for (uint64_t e = rp[u]; e < rp[u + 1]; e++) adj[pos[col[e]]++] = (uint32_t)u;
  // then out-neighbors (all > v, already sorted).
#pragma omp parallel for schedule(dynamic, 4096)
  for (uint64_t v = 0; v < n; v++) {
    uint64_t p = pos[v];
    for (uint64_t e = rp[v]; e < rp[v + 1]; e++) adj[p++] = col[e];
    if (p != off[v + 1]) { fprintf(stderr, "fill mismatch at %llu\n", (unsigned long long)v); exit(3); }
  }

  // GBBS "Total work" statistic on the repo's orientation.
  uint64_t work = 0;
#pragma omp parallel for schedule(dynamic, 4096) reduction(+ : work)
  for (uint64_t u = 0; u < n; u++)
    for (uint64_t e = rp[u]; e < rp[u + 1]; e++) work += rp[col[e] + 1] - rp[col[e]];

  FILE* o = fopen(argv[2], "wb");
  if (!o) die("open output");
  int64_t h[3] = {(int64_t)n, (int64_t)M,
                  (int64_t)(3 * 8 + (n + 1) * 8 + M * 4)};
  if (fwrite(h, 8, 3, o) != 3) die("write header");
  if (fwrite(off.data(), 8, n + 1, o) != n + 1) die("write offsets");
  if (M && fwrite(adj.data(), 4, M, o) != M) die("write edges");
  if (fclose(o) != 0) die("close output");

  printf("{\"n\": %llu, \"m_undirected\": %llu, \"m_directed\": %llu, "
         "\"max_forward_degree\": %llu, \"repo_dag_total_work\": %llu}\n",
         (unsigned long long)n, (unsigned long long)m, (unsigned long long)M,
         (unsigned long long)maxfwd, (unsigned long long)work);
  return 0;
}
