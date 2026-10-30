"""검증된 준비 배열의 불변 캐시. 장치 코드·시간 경계와 독립적이다."""
import fcntl,hashlib,json,os,subprocess,tempfile
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(16<<20),b''):h.update(b)
    return h.hexdigest()

def signature(command,input_sha):
    assert len(command)==5,'CPU oracle execution is never cached'
    mode=int(command[3]);mode={7:3,8:2,9:6,10:6}.get(mode,mode)
    return dict(version=1,input_sha256=input_sha,prepare_binary_sha256=sha(command[0]),mode=mode,tail=int(command[4]))

def entry_path(root,sig):
    key=hashlib.sha256(json.dumps(sig,sort_keys=True).encode()).hexdigest()
    return Path(root)/key

def publish(entry,output,info,sig,digest,command):
    staging=Path(tempfile.mkdtemp(prefix='.staging-',dir=entry.parent))
    os.link(output,staging/'aux.bin');os.chmod(staging/'aux.bin',0o444)
    meta=dict(signature=sig,aux_sha256=digest,bytes=output.stat().st_size,info=info,origin_command=command)
    (staging/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
    os.rename(staging,entry)

def prepare_aux(command,input_sha,root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    output=Path(command[2]);assert not output.exists()
    sig=signature(command,input_sha);entry=entry_path(root,sig)
    with (root/(entry.name+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if entry.exists():
            meta=json.loads((entry/'metadata.json').read_text());data=entry/'aux.bin'
            assert meta['signature']==sig,'prepare cache signature mismatch'
            assert data.stat().st_size==meta['bytes'],'prepare cache size mismatch'
            digest=sha(data);assert digest==meta['aux_sha256'],'prepare cache hash mismatch'
            os.link(data,output);info=meta['info'];state='hit'
        else:
            info=json.loads(subprocess.check_output(command,text=True));digest=sha(output)
            publish(entry,output,info,sig,digest,command);state='miss'
    return info,dict(status=state,entry=str(entry),signature=sig,aux_sha256=digest,bytes=output.stat().st_size)
