#pragma once
// gap/direct: the TT execution changes measured on TRUST (gap/GAP_RESULTS.md step B), applied
// to other GPU-derived ports. Work ownership, candidate sets and intersection methods are those
// of the baseline levels (StepTC opt2, WeTriC opt2, TriCore-COO opt3); only how rows reach SRAM,
// the StepTC high-degree membership structure, and probe grouping change.
//   io.fetch(which,lo,hi,dst): issue async reads of words [lo&~15,(hi+15)&~15) into dst and
//   return dst+lo%16; io.wait(): one barrier for everything issued since the last wait.
//   HASH_OA       StepTC degree>128 rows: TriMA open addressing instead of prefix-packed bins
//   BRANCHLESS    replace early-exit searches with fixed-shape searches run LOOKUP_WIDTH keys
//                 in lockstep (BRANCHLESS=1, LOOKUP_WIDTH=1 isolates the search rewrite itself)
//   TC_CHUNK/TC_HELD/TC_BOUND  TriCore opt3's three changes as independent switches (MODE 10)
#ifndef HASH_OA
#define HASH_OA 0
#endif
#ifndef BRANCHLESS
#define BRANCHLESS 0
#endif
#ifndef LOOKUP_WIDTH
#define LOOKUP_WIDTH 1
#endif
#ifndef META_STAGE
#define META_STAGE 64
#endif
#ifndef ARENA_WORDS
#define ARENA_WORDS 16384
#endif
#ifndef HASH_SIZE
#define HASH_SIZE 16384
#endif
#ifndef TC_CHUNK
#define TC_CHUNK 32
#endif
#ifndef TC_HELD
#define TC_HELD 1
#endif
#ifndef TC_BOUND
#define TC_BOUND 1
#endif

struct RowRef {uint32_t lo,hi,off,pad;};
// Scratch carve-up; every buffer starts on a 16-word (64 B) boundary for NoC reads.
struct Carve {
    uint32_t* p;
    uint32_t* take(uint32_t words){uint32_t* r=p;p+=(words+15)/16*16;return r;}
};
// Row-pointer pairs for ids[0..cnt): one barrier for the whole batch.
template<class IO> void fetch_pairs(IO& io,uint32_t which,const uint32_t* ids,uint32_t cnt,uint32_t* meta,RowRef* refs){
    io.metadata_batch();
    for(uint32_t k=0;k<cnt;k++){uint32_t v=ids[k];io.fetch(which,v,v+2,meta+k*32);}
    io.wait();
    for(uint32_t k=0;k<cnt;k++){uint32_t v=ids[k];refs[k].lo=meta[k*32+v%16];refs[k].hi=meta[k*32+v%16+1];}
}
// Exact column ranges of refs[k..) until the arena is full, then one barrier. Returns next k.
template<class IO> uint32_t fetch_rows(IO& io,RowRef* refs,uint32_t k,uint32_t cnt,uint32_t* arena,Counters& s){
    io.target_batch();
    uint32_t words=0;
    for(;k<cnt;k++){uint32_t lo=refs[k].lo,hi=refs[k].hi;
        if(hi<lo){s.error=4;return cnt;}
        if(hi==lo){refs[k].off=0;continue;}
        uint32_t need=((hi+15)&~15u)-(lo&~15u);
        if(need>ARENA_WORDS){s.error=20;return cnt;}
        if(words+need>ARENA_WORDS)break;
        io.fetch(1,lo,hi,arena+words);refs[k].off=words+lo%16;words+=need;
    }
    io.wait();return k;
}
// Fixed-shape membership search of W keys in sorted data[0,len): invariant answer in [b,b+nn).
template<uint32_t W> inline uint32_t lockstep_member(const uint32_t* data,uint32_t len,const uint32_t* keys,Counters& s){
    if(!len)return 0;
    uint32_t b[W];for(uint32_t z=0;z<W;z++)b[z]=0;
    for(uint32_t nn=len;nn>1;){uint32_t half=nn/2;
#pragma GCC unroll 8
        for(uint32_t z=0;z<W;z++){b[z]=data[b[z]+half]<=keys[z]?b[z]+half:b[z];}
        nn-=half;s.probes+=W;}
    uint32_t c=0;for(uint32_t z=0;z<W;z++)c+=data[b[z]]==keys[z];return c;
}

// ---- StepTC (opt2 semantics: no range bound; low rows monotone binary search, high rows hash)
template<class IO> Counters steptc_direct(IO& io,uint32_t n,uint32_t id,uint32_t engines,uint32_t* scratch,uint32_t cap){
    Counters s;Carve cv{scratch};
    uint32_t* arena=cv.take(ARENA_WORDS);uint32_t* meta=cv.take(META_STAGE*32);auto refs=(RowRef*)cv.take(META_STAGE*4);
    uint32_t* tasks=cv.take(META_STAGE+32);uint32_t* srcbuf=cv.take(cap+32);uint32_t* pairs=cv.take(64);
#if HASH_OA
    uint32_t* hash=cv.take(HASH_SIZE);uint32_t* used=cv.take(cap);uint32_t nused=0;
    for(uint32_t i=0;i<HASH_SIZE;i++)hash[i]=0;
#else
    uint32_t* offsets=cv.take(1022);uint32_t* cursor=cv.take(1022);uint32_t* packed=cv.take(cap);
#endif
    for(uint64_t uu=id;uu<n;uu+=engines){uint32_t u=uu;
        io.fetch(2,u,u+2,pairs);io.fetch(0,u,u+2,pairs+32);io.wait();
        uint32_t first=pairs[u%16],last=pairs[u%16+1];
        if(first==last)continue;
        uint32_t a=pairs[32+u%16],degree=pairs[32+u%16+1]-a;
        if(degree>cap){s.error=1;return s;}++s.jobs;
        const uint32_t* source=io.fetch(1,a,a+degree,srcbuf);io.wait();
#if !HASH_OA
        uint32_t bins=degree<=1024?511:1021;
#endif
        if(degree>128){
#if HASH_OA
            for(uint32_t k=0;k<nused;k++)hash[used[k]]=0;
            nused=0;
            for(uint32_t j=0;j<degree;j++){uint32_t y=source[j],key=y+1,slot=(y^(y>>16))&(HASH_SIZE-1);
                while(hash[slot]&&hash[slot]!=key)slot=(slot+1)&(HASH_SIZE-1);
                if(!hash[slot]){hash[slot]=key;used[nused++]=slot;}}
#else
            for(uint32_t j=0;j<=bins;j++)offsets[j]=0;
            for(uint32_t j=0;j<degree;j++)++offsets[source[j]%bins+1];
            for(uint32_t j=1;j<=bins;j++)offsets[j]+=offsets[j-1];
            for(uint32_t j=0;j<bins;j++)cursor[j]=offsets[j];
            for(uint32_t j=0;j<degree;j++)packed[cursor[source[j]%bins]++]=source[j];
#endif
        }
        for(uint32_t t0=first;t0<last;t0+=META_STAGE){
            uint32_t cnt=minimum(META_STAGE,last-t0);
            const uint32_t* tk=io.fetch(2,uint64_t(n)+1+t0,uint64_t(n)+1+t0+cnt,tasks);io.wait();
            fetch_pairs(io,0,tk,cnt,meta,refs);
            for(uint32_t k=0;k<cnt;){
                uint32_t k1=fetch_rows(io,refs,k,cnt,arena,s);if(s.error)return s;
                for(uint32_t q=k;q<k1;q++){
                    uint32_t len=refs[q].hi-refs[q].lo;const uint32_t* t=arena+refs[q].off;uint32_t x=0;
                    s.candidates+=len;
                    if(degree<=128){
#if BRANCHLESS
                        // Lockstep groups search source[lower,degree); lower advances monotonically per group.
                        uint32_t lower=0;
                        for(;x+LOOKUP_WIDTH<=len;x+=LOOKUP_WIDTH){
                            uint32_t b[LOOKUP_WIDTH];for(uint32_t z=0;z<LOOKUP_WIDTH;z++)b[z]=lower;
                            for(uint32_t nn=degree-lower;nn>1;){uint32_t half=nn/2;
#pragma GCC unroll 8
                                for(uint32_t z=0;z<LOOKUP_WIDTH;z++){b[z]=source[b[z]+half]<=t[x+z]?b[z]+half:b[z];}
                                nn-=half;s.probes+=LOOKUP_WIDTH;}
                            for(uint32_t z=0;z<LOOKUP_WIDTH;z++)s.count+=(lower<degree&&source[b[z]]==t[x+z]);
                            lower=b[LOOKUP_WIDTH-1];
                        }
                        for(;x<len;x++){uint32_t key=t[x],b=lower;
                            for(uint32_t nn=degree-lower;nn>1;){uint32_t half=nn/2;b=source[b+half]<=key?b+half:b;nn-=half;++s.probes;}
                            s.count+=(lower<degree&&source[b]==key);lower=b;}
#else
                        uint32_t lower=0;
                        for(;x<len;x++){uint32_t key=t[x],lo=lower,hi=degree;
                            while(lo<hi){uint32_t mid=(lo+hi)/2;++s.probes;if(source[mid]<key)lo=mid+1;else hi=mid;}
                            if(lo<degree&&source[lo]==key){++s.count;}lower=lo;}
#endif
                    }else{
#if HASH_OA
#if LOOKUP_WIDTH > 1
                        for(;x+LOOKUP_WIDTH<=len;x+=LOOKUP_WIDTH){
                            uint32_t keys[LOOKUP_WIDTH],slots[LOOKUP_WIDTH],values[LOOKUP_WIDTH];
#pragma GCC unroll 8
                            for(uint32_t z=0;z<LOOKUP_WIDTH;z++){uint32_t y=t[x+z];keys[z]=y+1;slots[z]=(y^(y>>16))&(HASH_SIZE-1);values[z]=hash[slots[z]];}
#pragma GCC unroll 8
                            for(uint32_t z=0;z<LOOKUP_WIDTH;z++){uint32_t v=values[z],slot=slots[z];while(v&&v!=keys[z]){slot=(slot+1)&(HASH_SIZE-1);v=hash[slot];++s.probes;}if(v==keys[z])++s.count;}
                        }
#endif
                        for(;x<len;x++){uint32_t y=t[x],key=y+1,slot=(y^(y>>16))&(HASH_SIZE-1),v;
                            while((v=hash[slot])&&v!=key){slot=(slot+1)&(HASH_SIZE-1);++s.probes;}if(v==key)++s.count;}
#else
                        for(;x<len;x++){uint32_t key=t[x],bin=key%bins;
                            for(uint32_t p=offsets[bin];p<offsets[bin+1];p++){++s.probes;if(packed[p]==key){++s.count;break;}}}
#endif
                    }
                }
                k=k1;
            }
        }
    }return s;
}

// ---- WeTriC (opt2 semantics: tail 0, wedge chunks of `spread`, search w in N(v))
template<class IO> Counters wetric_direct(IO& io,uint32_t n,uint32_t id,uint32_t engines,uint32_t spread,uint32_t* scratch,uint32_t cap){
    Counters s;Carve cv{scratch};
    uint32_t* arena=cv.take(ARENA_WORDS);uint32_t* meta=cv.take(META_STAGE*32);auto refs=(RowRef*)cv.take(META_STAGE*4);
    uint32_t* ids=cv.take(META_STAGE);uint32_t* kf=cv.take(META_STAGE);uint32_t* kt=cv.take(META_STAGE);uint32_t* ubuf=cv.take(cap+32);
    uint64_t total=prefix(io,n);uint32_t held_u=0xffffffffu;const uint32_t* row_u=ubuf;
    for(uint64_t start=uint64_t(id)*spread;start<total;start+=uint64_t(engines)*spread){
        uint32_t lo=0,hi=n;while(lo<hi){uint32_t mid=lo+(hi-lo)/2;if(prefix(io,mid+1)<=start)lo=mid+1;else hi=mid;}
        uint32_t u=lo,base=io.r(u),degree=io.r(u+1)-base;
        uint64_t index=start-prefix(io,u);uint32_t l=0,r=degree-1;
        while(l+1<r){uint32_t mid=(l+r)/2;if(wedge_row_start(degree,mid)<=index)l=mid;else r=mid;}
        uint32_t j=l,k=uint32_t(index-wedge_row_start(degree,j))+j+1;
        uint64_t q=start,stop=start+spread;if(stop>total)stop=total;
        while(q<stop){
            if(degree>cap){s.error=1;return s;}
            if(held_u!=u){row_u=io.fetch(1,base,base+degree,ubuf);io.wait();held_u=u;}
            uint32_t cnt=0;
            while(q<stop&&cnt<META_STAGE&&j+1<degree){
                uint64_t take=degree-k;if(take>stop-q)take=stop-q;
                ids[cnt]=row_u[j];kf[cnt]=k;kt[cnt]=k+uint32_t(take);++cnt;
                q+=take;k+=uint32_t(take);if(k>=degree){++j;k=j+1;}
            }
            fetch_pairs(io,0,ids,cnt,meta,refs);
            for(uint32_t e=0;e<cnt;){
                uint32_t e1=fetch_rows(io,refs,e,cnt,arena,s);if(s.error)return s;
                for(uint32_t p=e;p<e1;p++){
                    uint32_t len=refs[p].hi-refs[p].lo;const uint32_t* row=arena+refs[p].off;uint32_t x=kf[p];
                    s.jobs+=kt[p]-kf[p];s.candidates+=kt[p]-kf[p];
#if BRANCHLESS
                    for(;x+LOOKUP_WIDTH<=kt[p];x+=LOOKUP_WIDTH)s.count+=lockstep_member<LOOKUP_WIDTH>(row,len,row_u+x,s);
                    for(;x<kt[p];x++)s.count+=lockstep_member<1>(row,len,row_u+x,s);
#else
                    for(;x<kt[p];x++)if(local_search(row,0,len,row_u[x],s))++s.count;
#endif
                }
                e=e1;
            }
            if(q<stop&&j+1>=degree){do{++u;base=io.r(u);degree=io.r(u+1)-base;}while(degree<2);j=0;k=1;}
        }
    }return s;
}

// ---- TriCore over COO (opt3 semantics: 32-edge chunks, long-row sample reuse, range bound)
template<class IO> uint32_t tricore_keys(const uint32_t* row,uint32_t length,const uint32_t* samples,const uint32_t* keys,uint32_t nk,Counters& s){
    uint32_t c=0,x=0;
#if BRANCHLESS
    for(;x+LOOKUP_WIDTH<=nk;x+=LOOKUP_WIDTH){
        uint32_t b[LOOKUP_WIDTH],beg[LOOKUP_WIDTH],nn[LOOKUP_WIDTH],found[LOOKUP_WIDTH];
        for(uint32_t z=0;z<LOOKUP_WIDTH;z++)b[z]=0;
        for(uint32_t st=16;st;st>>=1){
#pragma GCC unroll 8
            for(uint32_t z=0;z<LOOKUP_WIDTH;z++){b[z]=samples[b[z]+st]<=keys[x+z]?b[z]+st:b[z];}
            s.probes+=LOOKUP_WIDTH;}
        uint32_t active=0;
        for(uint32_t z=0;z<LOOKUP_WIDTH;z++){found[z]=samples[b[z]]==keys[x+z];
            beg[z]=uint64_t(b[z])*length/32;nn[z]=found[z]?0:uint32_t(uint64_t(b[z]+1)*length/32)-beg[z];if(nn[z]>active)active=nn[z];}
        for(;active>1;){uint32_t next=0;
#pragma GCC unroll 8
            for(uint32_t z=0;z<LOOKUP_WIDTH;z++){if(nn[z]>1){uint32_t half=nn[z]/2;beg[z]=row[beg[z]+half]<=keys[x+z]?beg[z]+half:beg[z];nn[z]-=half;++s.probes;}if(nn[z]>next)next=nn[z];}
            active=next;}
        for(uint32_t z=0;z<LOOKUP_WIDTH;z++)c+=found[z]||(nn[z]==1&&row[beg[z]]==keys[x+z]);
    }
    for(;x<nk;x++){uint32_t key=keys[x],b=0;
        for(uint32_t st=16;st;st>>=1){b=samples[b+st]<=key?b+st:b;++s.probes;}
        if(samples[b]==key){++c;continue;}
        uint32_t beg=uint64_t(b)*length/32,nn=uint32_t(uint64_t(b+1)*length/32)-beg;
        for(;nn>1;){uint32_t half=nn/2;beg=row[beg+half]<=key?beg+half:beg;nn-=half;++s.probes;}
        c+=(nn==1&&row[beg]==key);}
#else
    for(;x<nk;x++){uint32_t key=keys[x],lo=0,hi=32;bool found=false;
        while(hi>lo+1){uint32_t mid=(hi+lo)/2,y=samples[mid];++s.probes;
            if(y==key){found=true;break;}if(y<key)lo=mid;else hi=mid;}
        if(found||local_search(row,uint64_t(lo)*length/32,uint64_t(hi)*length/32,key,s))++c;}
#endif
    return c;
}
template<class IO> Counters tricore_coo_direct(IO& io,uint32_t n,uint32_t m,uint32_t id,uint32_t engines,uint32_t* scratch,uint32_t cap){
    Counters s;Carve cv{scratch};constexpr uint32_t chunk=32;static_assert(META_STAGE>=chunk,"chunk ids");
    uint32_t* arena=cv.take(ARENA_WORDS);uint32_t* meta=cv.take(META_STAGE*32);auto refs=(RowRef*)cv.take(META_STAGE*4);
    uint32_t* srcs=cv.take(chunk+32);uint32_t* cols=cv.take(chunk+32);uint32_t* upair=cv.take(32);uint32_t* ubuf=cv.take(cap+32);
    uint32_t* samples=cv.take(32);uint32_t* keys=cv.take(cap+16);
    uint32_t held_u=0xffffffffu,ulo=0,ulen=0;const uint32_t* urow=ubuf;const uint32_t* held_row=nullptr;uint32_t held_length=0;
    for(uint64_t first=uint64_t(id)*chunk;first<m;first+=uint64_t(engines)*chunk){
        uint64_t stop=first+chunk;if(stop>m)stop=m;uint32_t cnt=uint32_t(stop-first);
        const uint32_t* su=io.fetch(2,first,stop,srcs);const uint32_t* sv=io.fetch(1,first,stop,cols);io.wait();
        fetch_pairs(io,0,sv,cnt,meta,refs);
        for(uint32_t e=0;e<cnt;){
            uint32_t e1=fetch_rows(io,refs,e,cnt,arena,s);if(s.error)return s;
            for(uint32_t p=e;p<e1;p++){
                uint32_t u=su[p];
                if(u!=held_u){
                    io.fetch(0,u,u+2,upair);io.wait();ulo=upair[u%16];ulen=upair[u%16+1]-ulo;
                    if(ulen>cap){s.error=1;return s;}
                    urow=io.fetch(1,ulo,ulo+ulen,ubuf);io.wait();held_u=u;held_row=nullptr;
                }
                const uint32_t* vrow=arena+refs[p].off;uint32_t vlen=refs[p].hi-refs[p].lo;
                const uint32_t* lrow=urow;uint32_t length=ulen;const uint32_t* srow=vrow;uint32_t slen=vlen;
                if(ulen<vlen){lrow=vrow;length=vlen;srow=urow;slen=ulen;}
                ++s.jobs;if(!length||!slen)continue;
                if(lrow[0]>srow[slen-1]||lrow[length-1]<srow[0])continue;
                if(held_row!=lrow||held_length!=length){
                    for(uint32_t k=0;k<32;k++)samples[k]=lrow[uint64_t(k)*length/32];
                    held_row=(lrow==urow)?urow:nullptr;held_length=length;
                }
                uint32_t nk=0;
                for(uint32_t j=0;j<slen;j++){uint32_t key=srow[j];if(key<lrow[0])continue;if(key>lrow[length-1])break;keys[nk++]=key;}
                s.candidates+=nk;
                s.count+=tricore_keys<IO>(lrow,length,samples,keys,nk,s);
            }
            e=e1;
        }
    }return s;
}

// ---- TriCore-COO opt2 + opt3's three changes as independent switches (task 5 grid)
template<class IO> Counters tricore_coo_grid(IO& io,uint32_t n,uint32_t m,uint32_t id,uint32_t engines,uint32_t* scratch){
    Counters s;auto samples=scratch;auto row=scratch+32;
    constexpr uint32_t chunk=TC_CHUNK;
    uint32_t held_a=0xffffffffu,held_length=0;
    for(uint64_t first=uint64_t(id)*chunk;first<m;first+=uint64_t(engines)*chunk){
      uint32_t u=io.a(first);uint64_t stop=first+chunk;if(stop>m)stop=m;
      for(uint64_t e=first;e<stop;e++){
        if(chunk>1){while(io.r(u+1)<=e)++u;}
        uint32_t v=io.c(e);
        uint32_t a=io.r(u),ae=io.r(u+1),b=io.r(v),be=io.r(v+1);
        if(ae-a<be-b){uint32_t t=a;a=b;b=t;t=ae;ae=be;be=t;}
        ++s.jobs;uint32_t length=ae-a;if(!length||b==be)continue;
        if(TC_BOUND&&(io.c(a)>io.c(be-1)||io.c(ae-1)<io.c(b)))continue;
        if(!TC_HELD||held_a!=a||held_length!=length){
            copy_words(io,1,a,length,row);held_a=a;held_length=length;
            for(uint32_t k=0;k<32;k++)samples[k]=row[uint64_t(k)*length/32];
        }
        for(uint32_t j=b;j<be;){uint32_t size;const uint32_t* span=io.span(1,j,size);size=minimum(size,be-j);
            for(uint32_t k=0;k<size;k++,j++){
                uint32_t key=span[k],lo=0,hi=32;bool found=false;
                if(TC_BOUND){if(key<row[0])continue;if(key>row[length-1]){j=be;break;}}
                ++s.candidates;
                while(hi>lo+1){uint32_t mid=(hi+lo)/2,y=samples[mid];++s.probes;
                    if(y==key){found=true;break;}if(y<key)lo=mid;else hi=mid;}
                if(found||local_search(row,uint64_t(lo)*length/32,uint64_t(hi)*length/32,key,s))++s.count;
            }
        }
      }
    }return s;
}
