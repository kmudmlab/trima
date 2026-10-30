#pragma once
#include <stdint.h>

// Algorithmic ports, not CUDA execution emulation. The same functions are
// compiled by the CPU oracle test and by the TT data-movement compiler.
struct Counters {
    uint64_t count=0, jobs=0, candidates=0, probes=0;
    uint32_t error=0;
};
inline uint32_t minimum(uint32_t a,uint32_t b){return a<b?a:b;}
template<class IO> bool search(IO& io,uint32_t begin,uint32_t end,uint32_t key,Counters& s){
    while(begin<end){uint32_t mid=begin+(end-begin)/2,v=io.c(mid);++s.probes;
        if(v==key){return true;}if(v<key)begin=mid+1;else end=mid;}
    return false;
}
template<class IO> uint32_t edge_source(IO& io,uint32_t edge,uint32_t n){
    uint32_t lo=0,hi=n;while(lo<hi){uint32_t mid=lo+(hi-lo)/2;
        if(io.r(mid+1)<=edge)lo=mid+1;else hi=mid;}return lo;
}

// TriCore warp-binary: shorter row probes longer row through a 32-entry
// equispaced cache and then a bounded binary search. Source lookup replaces
// the GPU COO workload (no change to the edge-intersection identity).
template<class IO> Counters tricore(IO& io,uint32_t n,uint32_t m,uint32_t id,uint32_t engines,uint32_t* scratch){
    Counters s;
    for(uint64_t e=id;e<m;e+=engines){
        uint32_t u=edge_source(io,(uint32_t)e,n),v=io.c(e);
        uint32_t a=io.r(u),ae=io.r(u+1),b=io.r(v),be=io.r(v+1);
        if(ae-a<be-b){uint32_t t=a;a=b;b=t;t=ae;ae=be;be=t;}
        ++s.jobs;uint32_t length=ae-a;if(!length||b==be)continue;
        for(uint32_t k=0;k<32;k++)scratch[k]=io.c(a+uint64_t(k)*length/32);
        for(uint32_t j=b;j<be;j++){
            uint32_t key=io.c(j),lo=0,hi=32;bool found=false;++s.candidates;
            while(hi>lo+1){uint32_t mid=(hi+lo)/2,y=scratch[mid];++s.probes;
                if(y==key){found=true;break;}if(y<key)lo=mid;else hi=mid;}
            if(found||search(io,a+uint64_t(lo)*length/32,a+uint64_t(hi)*length/32,key,s))++s.count;
        }
    }
    return s;
}

template<class IO> uint64_t prefix(IO& io,uint32_t u){return uint64_t(io.a(2*u))+(uint64_t(io.a(2*u+1))<<32);}
inline uint64_t wedge_row_start(uint32_t degree,uint32_t j){return uint64_t(j)*(2*uint64_t(degree)-j-1)/2;}
// WeTriC outgoing-wedge enumeration, chunked linear wedge indices and exact
// integer inverse mapping. Replaces floating sqrt mapping to avoid rounding.
// Optional tail adjacency bitmap preserves the upstream membership shortcut.
template<class IO> Counters wetric(IO& io,uint32_t n,uint32_t id,uint32_t engines,uint32_t spread,uint32_t tail){
    Counters s;uint64_t total=prefix(io,n);uint32_t cut=n-tail;
    for(uint64_t start=uint64_t(id)*spread;start<total;start+=uint64_t(engines)*spread){
        uint32_t lo=0,hi=n;
        while(lo<hi){uint32_t mid=lo+(hi-lo)/2;if(prefix(io,mid+1)<=start)lo=mid+1;else hi=mid;}
        uint32_t u=lo,base=io.r(u),degree=io.r(u+1)-base;
        uint64_t index=start-prefix(io,u);uint32_t l=0,r=degree-1;
        while(l+1<r){uint32_t mid=(l+r)/2;if(wedge_row_start(degree,mid)<=index)l=mid;else r=mid;}
        uint32_t j=l,k=(uint32_t)(index-wedge_row_start(degree,j))+j+1;
        uint64_t stop=start+spread;if(stop>total)stop=total;
        for(uint64_t q=start;q<stop;q++){
            uint32_t v=io.c(base+j),w=io.c(base+k);++s.jobs;++s.candidates;
            if(tail&&v>=cut){
                uint64_t bit=uint64_t(v-cut)*(2*uint64_t(tail)-(v-cut)-1)/2+(w-v-1);
                s.count+=(io.a(2*(n+1)+bit/32)>>(bit%32))&1u;++s.probes;
            }else if(search(io,io.r(v),io.r(v+1),w,s))++s.count;
            if(++k>=degree){++j;k=j+1;}
            if(j+1>=degree&&q+1<stop){
                do {++u;base=io.r(u);degree=io.r(u+1)-base;}while(degree<2);
                j=0;k=1;
            }
        }
    }return s;
}

// StepTC task ownership: low-low edges follow original orientation; edges
// incident to a high forward-degree row are owned by the larger forward row.
// The auxiliary CSR contains these tasks. Low rows use monotone binary search;
// high rows use compact 511/1021-bucket hashes with prefix-packed contents.
template<class IO> Counters steptc(IO& io,uint32_t n,uint32_t id,uint32_t engines,uint32_t* scratch,uint32_t cap){
    Counters s;uint32_t* source=scratch;uint32_t* offsets=source+cap;uint32_t* cursor=offsets+1022;uint32_t* packed=cursor+1022;
    for(uint64_t uu=id;uu<n;uu+=engines){uint32_t u=uu,first=io.a(u),last=io.a(u+1);
        if(first==last){continue;}uint32_t a=io.r(u),degree=io.r(u+1)-a;
        if(degree>cap){s.error=1;return s;}++s.jobs;
        for(uint32_t j=0;j<degree;j++)source[j]=io.c(a+j);
        uint32_t bins=degree<=1024?511:1021;
        if(degree>128){
            for(uint32_t j=0;j<=bins;j++)offsets[j]=0;
            for(uint32_t j=0;j<degree;j++)++offsets[source[j]%bins+1];
            for(uint32_t j=1;j<=bins;j++)offsets[j]+=offsets[j-1];
            for(uint32_t j=0;j<bins;j++)cursor[j]=offsets[j];
            for(uint32_t j=0;j<degree;j++)packed[cursor[source[j]%bins]++]=source[j];
        }
        for(uint32_t t=first;t<last;t++){uint32_t v=io.a(n+1+t),begin=io.r(v),end=io.r(v+1),lower=0;
            for(uint32_t j=begin;j<end;j++){uint32_t key=io.c(j);++s.candidates;
                if(degree<=128){uint32_t lo=lower,hi=degree;
                    while(lo<hi){uint32_t mid=(lo+hi)/2;++s.probes;if(source[mid]<key)lo=mid+1;else hi=mid;}
                    if(lo<degree&&source[lo]==key){++s.count;}lower=lo;
                }else{uint32_t bin=key%bins;
                    for(uint32_t q=offsets[bin];q<offsets[bin+1];q++){++s.probes;if(packed[q]==key){++s.count;break;}}
                }
            }
        }
    }return s;
}

inline uint32_t pop32(uint32_t x){
    x-=((x>>1)&0x55555555u);x=(x&0x33333333u)+((x>>2)&0x33333333u);
    x=(x+(x>>4))&0x0f0f0f0fu;x+=x>>8;x+=x>>16;return x&63u;
}
// BTC-TC V5 representation and online matching, scalar instruction adaptation.
// The >64/512 density decision is retained. Dense BMMA is explicitly emulated
// using full 16x16 AND/popcount; sparse only visits mask bits. This variant is
// not a claim that TT has the NVIDIA b1 BMMA instruction or an optimized hybrid.
template<class IO> Counters btc_scalar(IO& io,uint32_t id,uint32_t engines){
    Counters s;uint32_t nr=io.a(0),nb=io.a(1),ip=2,ix=ip+nr+1,bits=ix+nb;
    for(uint64_t sample=id;sample<nb;sample+=engines){
        uint32_t lo=0,hi=nr;while(lo<hi){uint32_t mid=(lo+hi)/2;if(io.a(ip+mid+1)<=sample)lo=mid+1;else hi=mid;}
        uint32_t i=lo,j=io.a(ix+sample),mask[16],nnz=0;++s.jobs;
        for(uint32_t r=0;r<16;r++){mask[r]=io.a(bits+sample*16+r);nnz+=pop32(mask[r]);}
        bool dense=nnz>64;
        for(uint32_t half=0;half<2;half++){
            uint32_t jrow=j*2+half;if(jrow>=nr)continue;
            uint32_t a=io.a(ip+i),ae=io.a(ip+i+1),b=io.a(ip+jrow),be=io.a(ip+jrow+1);
            while(a<ae&&b<be){uint32_t ak=io.a(ix+a),bk=io.a(ix+b);++s.probes;
                if(ak<bk){++a;continue;}if(bk<ak){++b;continue;}
                uint32_t av[16],bv[16];for(uint32_t r=0;r<16;r++){av[r]=io.a(bits+a*16+r);bv[r]=io.a(bits+b*16+r);}
                for(uint32_t r=0;r<16;r++)for(uint32_t c=0;c<16;c++){
                    bool active=(mask[r]>>(half*16+c))&1u;
                    if(dense||active){++s.candidates;uint32_t v=pop32(av[r]&bv[c]);if(active)s.count+=v;}
                }
                ++a;++b;
            }
        }
    }return s;
}
