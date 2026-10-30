"""Bounded pre-measurement wait. Never signals device owners."""
import json,os,subprocess,time
from pathlib import Path

def owner_info(pid):
    result={'pid':pid}
    try:
        p=Path('/proc')/str(pid)
        result['cmdline']=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace').strip()
        for line in (p/'status').read_text().splitlines():
            if line.startswith('Uid:'):result['uid']=int(line.split()[1])
            if line.startswith('PPid:'):result['ppid']=int(line.split()[1])
    except (OSError,ValueError) as exc:result['inspection_error']=type(exc).__name__
    return result

def wait_device_free(receipt,stage,timeout=120.0,interval=1.0):
    receipt=Path(receipt);start=time.monotonic();events=[];waits=0
    def save(status,**extra):
        data=dict(status=status,stage=stage,timeout_s=timeout,interval_s=interval,
                  wait_count=waits,checks=len(events),administrative_wait_s=time.monotonic()-start,
                  events=events,signals_sent=False,**extra)
        tmp=receipt.with_suffix(receipt.suffix+'.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(receipt)
    while True:
        r=subprocess.run(['fuser','/dev/tenstorrent/0'],capture_output=True,text=True)
        if r.returncode not in (0,1):
            save('check_error',returncode=r.returncode,stderr=r.stderr)
            raise RuntimeError(('device ownership check failed',r.returncode,r.stderr))
        pids=sorted({int(p) for p in r.stdout.split()}-{os.getpid()})
        events.append(dict(check=len(events),owners=[owner_info(pid) for pid in pids]))
        if not pids:save('free');return
        remaining=timeout-(time.monotonic()-start)
        if remaining<=0:
            save('timeout');raise RuntimeError(('device occupied timeout',pids,timeout))
        save('waiting');time.sleep(min(interval,remaining));waits+=1
