#!/bin/sh
# Rebuild the GPU kernel sources used in the paper from the authors' public repositories.
# TRUST, TriCore and WeTriC carry no license file, so only patches against pinned commits are shipped.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-"$HERE/build-src"}
mkdir -p "$OUT/upstream"
fetch() {  # name url commit
  [ -d "$OUT/upstream/$1" ] || git clone -q "$2" "$OUT/upstream/$1"
  git -C "$OUT/upstream/$1" checkout -q "$3"
}
fetch TRUST   https://github.com/wzbxpy/TRUST.git 90845c6df63673569c7cb87aaa8c8499023d83a0
fetch TriCore https://github.com/huyang1988/TC.git adcbf043baab8fff544daa597ccb956ddd094d39
fetch WeTriC  https://github.com/jeffreyspaan/wedge-parallel-triangle-counting.git f0c80447dc428ead5f8a41f2f1d9c4c4cbc41c2e
patch -s -o "$OUT/trust_kernel.cuh"   "$OUT/upstream/TRUST/Without-graph-partition/TC.cu" "$HERE/upstream-patches/trust.patch"
patch -s -o "$OUT/tricore_kernel.cuh" "$OUT/upstream/TriCore/TC-GPU/tc-inmemory-heterogeneous/static/scan.cu" "$HERE/upstream-patches/tricore.patch"
patch -s -o "$OUT/wetric_instrumented.cu" "$OUT/upstream/WeTriC/tc.cu" "$HERE/upstream-patches/wetric.patch"
cp "$HERE/drivers/gpu_baselines_driver.cu" "$HERE/drivers/wetric_driver.cu" "$OUT/"
cp "$HERE/steptc/"* "$OUT/"
(cd "$OUT" && sha256sum trust_kernel.cuh tricore_kernel.cuh wetric_instrumented.cu) | diff - "$HERE/SOURCES.sha256" \
  && echo "sources match the ones the paper's binaries were built from"
