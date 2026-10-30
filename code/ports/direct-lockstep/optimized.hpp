#pragma once
// 0 = retained algorithm; 1 = explicit row staging (BTC: index staging);
// 2 = staging + page-span access (BTC: adaptive matching and mask-only work).
#ifndef OPT_LEVEL
#define OPT_LEVEL 0
#endif
#ifndef BTC_ADAPTIVE
#define BTC_ADAPTIVE 1
#endif
#ifndef BTC_MASKONLY
#define BTC_MASKONLY 1
#endif
template<class IO> void copy_words(IO& io,uint32_t which,uint32_t begin,uint32_t size,uint32_t* dst){
    if(OPT_LEVEL<2){for(uint32_t i=0;i<size;i++)dst[i]=io.get(which,begin+i);return;}
    for(uint32_t i=0;i<size;){uint32_t len;auto p=io.span(which,begin+i,len);len=minimum(len,size-i);
        for(uint32_t k=0;k<len;k++){dst[i+k]=p[k];}i+=len;}
}
inline bool local_search(const uint32_t* data,uint32_t begin,uint32_t end,uint32_t key,Counters& s){
    while(begin<end){uint32_t mid=begin+(end-begin)/2,v=data[mid];++s.probes;
        if(v==key){return true;}if(v<key)begin=mid+1;else end=mid;}return false;
}
template<class IO> Counters tricore_staged(IO& io,uint32_t n,uint32_t m,uint32_t id,uint32_t engines,uint32_t* scratch){
    Counters s;auto samples=scratch;auto row=scratch+32;
    constexpr uint32_t chunk=OPT_LEVEL>=3?32:1;
    uint32_t held_a=0xffffffffu,held_length=0;
    for(uint64_t first=uint64_t(id)*chunk;first<m;first+=uint64_t(engines)*chunk){
      uint32_t u=edge_source(io,first,n);uint64_t stop=first+chunk;if(stop>m)stop=m;
      for(uint64_t e=first;e<stop;e++){
        if(OPT_LEVEL>=3){while(io.r(u+1)<=e)++u;}
        uint32_t v=io.c(e);
        uint32_t a=io.r(u),ae=io.r(u+1),b=io.r(v),be=io.r(v+1);
        if(ae-a<be-b){uint32_t t=a;a=b;b=t;t=ae;ae=be;be=t;}
        ++s.jobs;uint32_t length=ae-a;if(!length||b==be)continue;
        if(OPT_LEVEL>=3&&(io.c(a)>io.c(be-1)||io.c(ae-1)<io.c(b)))continue;
        if(OPT_LEVEL<3||held_a!=a||held_length!=length){
            copy_words(io,1,a,length,row);held_a=a;held_length=length;
            for(uint32_t k=0;k<32;k++)samples[k]=row[uint64_t(k)*length/32];
        }
        for(uint32_t j=b;j<be;){uint32_t size=1;const uint32_t* span=nullptr;
            if(OPT_LEVEL>=2){span=io.span(1,j,size);size=minimum(size,be-j);}
            for(uint32_t k=0;k<size;k++,j++){
                uint32_t key=span?span[k]:io.c(j),lo=0,hi=32;bool found=false;
                if(OPT_LEVEL>=3){if(key<row[0])continue;if(key>row[length-1]){j=be;break;}}
                ++s.candidates;
                while(hi>lo+1){uint32_t mid=(hi+lo)/2,y=samples[mid];++s.probes;
                    if(y==key){found=true;break;}if(y<key)lo=mid;else hi=mid;}
                if(found||local_search(row,uint64_t(lo)*length/32,uint64_t(hi)*length/32,key,s))++s.count;
            }
        }
      }
    }return s;
}
template<class IO> Counters wetric_staged(IO& io,uint32_t n,uint32_t id,uint32_t engines,uint32_t spread,uint32_t tail,uint32_t* scratch){
    Counters s;uint64_t total=prefix(io,n);uint32_t cut=n-tail,held=0xffffffffu,held_size=0;
    for(uint64_t start=uint64_t(id)*spread;start<total;start+=uint64_t(engines)*spread){
        uint32_t lo=0,hi=n;while(lo<hi){uint32_t mid=lo+(hi-lo)/2;if(prefix(io,mid+1)<=start)lo=mid+1;else hi=mid;}
        uint32_t u=lo,base=io.r(u),degree=io.r(u+1)-base;
        uint64_t index=start-prefix(io,u);uint32_t l=0,r=degree-1;
        while(l+1<r){uint32_t mid=(l+r)/2;if(wedge_row_start(degree,mid)<=index)l=mid;else r=mid;}
        uint32_t j=l,k=uint32_t(index-wedge_row_start(degree,j))+j+1;
        uint64_t stop=start+spread;if(stop>total)stop=total;
        for(uint64_t q=start;q<stop;q++){
            uint32_t v=io.c(base+j),w=io.c(base+k);++s.jobs;++s.candidates;
            if(tail&&v>=cut){uint64_t bit=uint64_t(v-cut)*(2*uint64_t(tail)-(v-cut)-1)/2+(w-v-1);
                s.count+=(io.a(2*(n+1)+bit/32)>>(bit%32))&1u;++s.probes;
            }else{
                if(held!=v){uint32_t first=io.r(v);held_size=io.r(v+1)-first;copy_words(io,1,first,held_size,scratch);held=v;}
                if(OPT_LEVEL<3||(held_size&&w>=scratch[0]&&w<=scratch[held_size-1])){
                    if(local_search(scratch,0,held_size,w,s))++s.count;}
            }
            if(++k>=degree){++j;k=j+1;}
            if(j+1>=degree&&q+1<stop){do{++u;base=io.r(u);degree=io.r(u+1)-base;}while(degree<2);j=0;k=1;}
        }
    }return s;
}
// TRUST's per-source hash reuse, with prefix-packed power-of-two buckets.
// Removes fixed bucket capacity, retaining source ownership and membership work.
template<class IO> Counters trust_packed(IO& io,uint32_t n,uint32_t id,uint32_t engines,uint32_t* scratch,uint32_t cap){
    Counters s;auto source=scratch;auto offsets=source+cap;auto cursor=offsets+1025;auto packed=cursor+1024;
    for(uint64_t u=id;u<n;u+=engines){uint32_t a=io.r(u),degree=io.r(u+1)-a;if(degree<2)continue;
        if(degree>cap){s.error=1;return s;}++s.jobs;copy_words(io,1,a,degree,source);
        uint32_t bins=degree>100?1024:32,mask=bins-1;
        for(uint32_t j=0;j<=bins;j++)offsets[j]=0;
        for(uint32_t j=0;j<degree;j++)++offsets[(source[j]&mask)+1];
        for(uint32_t j=1;j<=bins;j++)offsets[j]+=offsets[j-1];
        for(uint32_t j=0;j<bins;j++)cursor[j]=offsets[j];
        for(uint32_t j=0;j<degree;j++)packed[cursor[source[j]&mask]++]=source[j];
        for(uint32_t t=0;t<degree;t++){uint32_t v=source[t],begin=io.r(v),end=io.r(v+1);
            for(uint32_t j=begin;j<end;){uint32_t size=1;const uint32_t* span=nullptr;
                if(OPT_LEVEL>=2){span=io.span(1,j,size);size=minimum(size,end-j);}
                for(uint32_t k=0;k<size;k++,j++){uint32_t key=span?span[k]:io.c(j),bin=key&mask;
                    if(OPT_LEVEL>=3){if(key<source[0])continue;if(key>source[degree-1]){j=end;break;}}
                    ++s.candidates;
                    for(uint32_t q=offsets[bin];q<offsets[bin+1];q++){++s.probes;if(packed[q]==key){++s.count;break;}}
                }
            }
        }
    }return s;
}
struct IndexRow {uint32_t* data;uint32_t start,size;bool staged;};
template<class IO> uint32_t index_at(IO& io,const IndexRow& row,uint32_t ix,uint32_t j){return row.staged?row.data[j]:io.a(ix+row.start+j);}
template<class IO> void btc_product(IO& io,uint32_t bits,uint32_t a,uint32_t b,const uint32_t* mask,uint32_t half,bool dense,Counters& s){
    uint32_t av[16],bv[16];copy_words(io,2,bits+a*16,16,av);copy_words(io,2,bits+b*16,16,bv);
    for(uint32_t r=0;r<16;r++){
        if(OPT_LEVEL>=2&&BTC_MASKONLY){uint32_t active=(mask[r]>>(half*16))&65535u;
            while(active){uint32_t c=__builtin_ctz(active);active&=active-1;++s.candidates;s.count+=pop32(av[r]&bv[c]);}
        }else for(uint32_t c=0;c<16;c++){bool active=(mask[r]>>(half*16+c))&1u;
            if(dense||active){++s.candidates;uint32_t v=pop32(av[r]&bv[c]);if(active)s.count+=v;}}
    }
}
template<class IO> Counters btc_staged(IO& io,uint32_t id,uint32_t engines,uint32_t* scratch){
    Counters s;uint32_t nr=io.a(0),nb=io.a(1),ip=2,ix=ip+nr+1,bits=ix+nb;
    constexpr uint32_t capacity=8192;
    for(uint64_t sample=id;sample<nb;sample+=engines){
        uint32_t lo=0,hi=nr;while(lo<hi){uint32_t mid=(lo+hi)/2;if(io.a(ip+mid+1)<=sample)lo=mid+1;else hi=mid;}
        uint32_t i=lo,j=io.a(ix+sample),mask[16],nnz=0;++s.jobs;
        copy_words(io,2,bits+sample*16,16,mask);for(uint32_t r=0;r<16;r++)nnz+=pop32(mask[r]);
        uint32_t first=io.a(ip+i),size=io.a(ip+i+1)-first;IndexRow left{scratch,first,size,size<=capacity};
        if(left.staged)copy_words(io,2,ix+first,size,left.data);
        for(uint32_t half=0;half<2;half++){
            uint32_t jrow=j*2+half;if(jrow>=nr)continue;
            if(OPT_LEVEL>=2&&BTC_MASKONLY){uint32_t active=0;for(uint32_t r=0;r<16;r++)active|=mask[r]>>(half*16);if(!(active&65535u))continue;}
            first=io.a(ip+jrow);size=io.a(ip+jrow+1)-first;IndexRow right{scratch+capacity,first,size,size<=capacity};
            if(right.staged)copy_words(io,2,ix+first,size,right.data);
            IndexRow small=left,large=right;bool swapped=small.size>large.size;if(swapped){small=right;large=left;}
            uint32_t logsize=0;for(uint32_t x=large.size;x;x>>=1)++logsize;
            if(OPT_LEVEL>=2&&BTC_ADAPTIVE&&uint64_t(small.size)*logsize<left.size+right.size){
                uint32_t lower=0;
                for(uint32_t a=0;a<small.size;a++){
                    uint32_t key=index_at(io,small,ix,a),lo=lower,hi=large.size;
                    while(lo<hi){uint32_t mid=lo+(hi-lo)/2;++s.probes;if(index_at(io,large,ix,mid)<key)lo=mid+1;else hi=mid;}
                    lower=lo;if(lo==large.size)break;
                    if(index_at(io,large,ix,lo)==key){uint32_t ai=small.start+a,bi=large.start+lo;
                        btc_product(io,bits,swapped?bi:ai,swapped?ai:bi,mask,half,nnz>64,s);}
                }
            }else{
                uint32_t a=0,b=0;while(a<left.size&&b<right.size){uint32_t ak=index_at(io,left,ix,a),bk=index_at(io,right,ix,b);++s.probes;
                    if(ak<bk){++a;continue;}if(bk<ak){++b;continue;}
                    btc_product(io,bits,left.start+a,right.start+b,mask,half,nnz>64,s);++a;++b;}
            }
        }
    }return s;
}

// Stronger source lookup control: materialized COO source per edge.
template<class IO> Counters tricore_coo_original(IO& io,uint32_t n,uint32_t m,uint32_t id,uint32_t engines,uint32_t* scratch){
    Counters s;
    for(uint64_t e=id;e<m;e+=engines){
        uint32_t u=io.a((uint32_t)e),v=io.c(e);
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


template<class IO> Counters tricore_coo_staged(IO& io,uint32_t n,uint32_t m,uint32_t id,uint32_t engines,uint32_t* scratch){
    Counters s;auto samples=scratch;auto row=scratch+32;
    constexpr uint32_t chunk=OPT_LEVEL>=3?32:1;
    uint32_t held_a=0xffffffffu,held_length=0;
    for(uint64_t first=uint64_t(id)*chunk;first<m;first+=uint64_t(engines)*chunk){
      uint32_t u=io.a(first);uint64_t stop=first+chunk;if(stop>m)stop=m;
      for(uint64_t e=first;e<stop;e++){
        if(OPT_LEVEL>=3){while(io.r(u+1)<=e)++u;}
        uint32_t v=io.c(e);
        uint32_t a=io.r(u),ae=io.r(u+1),b=io.r(v),be=io.r(v+1);
        if(ae-a<be-b){uint32_t t=a;a=b;b=t;t=ae;ae=be;be=t;}
        ++s.jobs;uint32_t length=ae-a;if(!length||b==be)continue;
        if(OPT_LEVEL>=3&&(io.c(a)>io.c(be-1)||io.c(ae-1)<io.c(b)))continue;
        if(OPT_LEVEL<3||held_a!=a||held_length!=length){
            copy_words(io,1,a,length,row);held_a=a;held_length=length;
            for(uint32_t k=0;k<32;k++)samples[k]=row[uint64_t(k)*length/32];
        }
        for(uint32_t j=b;j<be;){uint32_t size=1;const uint32_t* span=nullptr;
            if(OPT_LEVEL>=2){span=io.span(1,j,size);size=minimum(size,be-j);}
            for(uint32_t k=0;k<size;k++,j++){
                uint32_t key=span?span[k]:io.c(j),lo=0,hi=32;bool found=false;
                if(OPT_LEVEL>=3){if(key<row[0])continue;if(key>row[length-1]){j=be;break;}}
                ++s.candidates;
                while(hi>lo+1){uint32_t mid=(hi+lo)/2,y=samples[mid];++s.probes;
                    if(y==key){found=true;break;}if(y<key)lo=mid;else hi=mid;}
                if(found||local_search(row,uint64_t(lo)*length/32,uint64_t(hi)*length/32,key,s))++s.count;
            }
        }
      }
    }return s;
}
