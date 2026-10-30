#pragma once
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <vector>
inline std::vector<uint32_t> pool,control_words,output_words;
inline std::mutex memory_mutex;
inline thread_local std::vector<uint32_t> scratch;
inline thread_local std::vector<uint32_t> args;
inline thread_local uint32_t engine_id;
struct Accessor {uint32_t* ptr;uint32_t page;};
struct Request {uint64_t src;uintptr_t dst;uint32_t bytes;};
inline thread_local std::vector<Request> pending;
template<typename T> T get_common_arg_val(uint32_t i) { return T(args.at(i)); }
inline uint32_t get_absolute_logical_x() { return (engine_id/args[4])%args[3]; }
inline uint32_t get_absolute_logical_y() { return (engine_id/args[4])/args[3]; }
inline uintptr_t get_write_ptr(uint32_t) { return uintptr_t(scratch.data()); }
inline uint64_t get_timestamp() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
inline uint64_t get_noc_addr(uint32_t page,const Accessor& a) { return uint64_t(uintptr_t(a.ptr))+uint64_t(page)*a.page; }
inline void noc_async_read(uint64_t src,uintptr_t dst,uint32_t bytes) {
    auto low=uintptr_t(scratch.data()),high=low+scratch.size()*4;
    if(dst<low || dst+bytes>high) { throw std::runtime_error("L1 range"); }
    for(const auto& p:pending) { if(dst<p.dst+p.bytes && p.dst<dst+bytes) { throw std::runtime_error("outstanding destinations overlap"); } }
    pending.push_back({src,dst,bytes});
}
inline void noc_async_read_tile(uint32_t pg,const Accessor& a,uintptr_t dst) { noc_async_read(get_noc_addr(pg,a),dst,a.page); }
inline void noc_async_read_barrier() {
    {std::lock_guard<std::mutex> guard(memory_mutex);for(const auto& p:pending) { std::memcpy((void*)p.dst,(const void*)uintptr_t(p.src),p.bytes); }pending.clear();}
    std::this_thread::yield();
}
inline void noc_async_write_tile(uint32_t pg,const Accessor& a,uintptr_t src) {
    std::lock_guard<std::mutex> guard(memory_mutex);std::memcpy((void*)uintptr_t(get_noc_addr(pg,a)),(void*)src,a.page);
}
inline void noc_async_write_barrier() { std::this_thread::yield(); }
