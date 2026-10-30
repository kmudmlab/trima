// Benchmark adapter; upstream WeTriC kernels are included without modification.
// wetric_instrumented.cu adds only a host-clock resident interval in tc_GPU.
#define main wetric_upstream_main
#include "wetric_instrumented.cu"
#undef main
#include <chrono>
#include <cuda_profiler_api.h>
#include <cassert>

static double seconds_now() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
static void write_cache(const char* path, GRAPH_TYPE* g) {
  FILE* f = fopen(path, "wb"); assert(f);
  assert(fwrite(&g->numVertices, 4, 1, f) == 1);
  assert(fwrite(&g->numEdges, 4, 1, f) == 1);
  assert(fwrite(g->rowPtr, 4, size_t(g->numVertices)+1, f) == size_t(g->numVertices)+1);
  assert(fwrite(g->colInd, 4, g->numEdges, f) == g->numEdges);
  assert(fclose(f) == 0);
}
static GRAPH_TYPE* read_cache(const char* path) {
  FILE* f = fopen(path, "rb"); assert(f);
  GRAPH_TYPE* g = (GRAPH_TYPE*)calloc(1, sizeof(GRAPH_TYPE)); assert(g);
  assert(fread(&g->numVertices, 4, 1, f) == 1);
  assert(fread(&g->numEdges, 4, 1, f) == 1);
  g->rowPtr = (UINT_t*)malloc(4*(size_t(g->numVertices)+1)); assert(g->rowPtr);
  g->colInd = (UINT_t*)malloc(4*size_t(g->numEdges)); assert(g->colInd);
  assert(fread(g->rowPtr, 4, size_t(g->numVertices)+1, f) == size_t(g->numVertices)+1);
  assert(fread(g->colInd, 4, g->numEdges, f) == g->numEdges);
  assert(fgetc(f) == EOF); fclose(f);
  return g;
}
static void validate(GRAPH_TYPE* g) {
  assert(g->rowPtr[0] == 0 && g->rowPtr[g->numVertices] == g->numEdges);
  uint32_t max_degree = 0;
  uint64_t wedges = 0;
  for (uint32_t u=0; u<g->numVertices; ++u) {
    assert(g->rowPtr[u] <= g->rowPtr[u+1]);
    uint32_t d = g->rowPtr[u+1]-g->rowPtr[u];
    max_degree = std::max(max_degree, d);
    wedges += uint64_t(d)*(d ? d-1 : 0)/2;
    for (uint32_t j=g->rowPtr[u]; j<g->rowPtr[u+1]; ++j) {
      assert(g->colInd[j] > u && g->colInd[j] < g->numVertices);
      if (j>g->rowPtr[u]) assert(g->colInd[j-1] < g->colInd[j]);
    }
  }
  assert(uint64_t(max_degree)*max_degree <= UINT32_MAX);
  printf("{\"kind\":\"structure\",\"n\":%u,\"m\":%u,\"max_degree\":%u,\"wedges\":%llu}\n",
    g->numVertices,g->numEdges,max_degree,(unsigned long long)wedges);
  fflush(stdout);
}
int main(int argc, char** argv) {
  assert(argc >= 4);
  if (strcmp(argv[1], "prepare") == 0) {
    double start=seconds_now();
    GRAPH_TYPE* raw=read_graph(argv[2], false, true, PREPROCESS_CPU);
    double loaded=seconds_now();
    GRAPH_TYPE* g=preprocess(raw, PREPROCESS_CPU); free_graph(raw);
    double prepared=seconds_now(); validate(g); write_cache(argv[3],g);
    printf("{\"kind\":\"prepare\",\"read_dedup_s\":%.9f,\"orient_s\":%.9f,\"total_s\":%.9f}\n",
      loaded-start,prepared-loaded,seconds_now()-start);
    free_graph(g); return 0;
  }
  assert(strcmp(argv[1], "run") == 0 && argc == 7);
  GRAPH_TYPE* g=read_cache(argv[2]); validate(g);
  unsigned spread=atoi(argv[3]), adjacency=atoi(argv[4]), reps=atoi(argv[5]);
  unsigned long long expected=strtoull(argv[6], nullptr, 10);
  assert(spread && adjacency%32==0 && reps>=1);
  cudaDeviceProp prop; checkCudaErrors(cudaGetDeviceProperties(&prop,0));
  printf("{\"kind\":\"device\",\"name\":\"%s\",\"memory_bytes\":%llu,\"sms\":%d}\n",
    prop.name,(unsigned long long)prop.totalGlobalMem,prop.multiProcessorCount);
  // The upstream routine reuploads and frees inputs each call. Resident wall
  // timing begins after upload and ends after the count readback; full_call_s
  // includes host auxiliary construction, allocations, upload, and teardown.
  for(unsigned i=0;i<=reps;++i) {
    GPU_time t={}; double start=seconds_now();
    if(i==1){checkCudaErrors(cudaProfilerStart());}
    unsigned long long count=tc_GPU(g,spread,adjacency,&t);
    if(i==1){checkCudaErrors(cudaProfilerStop());}
    double full=seconds_now()-start;
    printf("{\"kind\":\"sample\",\"warmup\":%s,\"count\":%llu,\"kernel_s\":%.9f,\"resident_s\":%.9f,\"upload_event_s\":%.9f,\"full_call_s\":%.9f,\"spread\":%u,\"adjacency\":%u}\n",
      i==0?"true":"false", count,t.exec/1000,t.resident,t.copy/1000,full,spread,adjacency);
    fflush(stdout); assert(count==expected);
  }
  free_graph(g); return 0;
}
