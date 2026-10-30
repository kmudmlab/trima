"""셀 시작 직전 GPU 점유를 검사하고 원문과 메모리 사용량을 보존한다."""
import datetime,json,subprocess,time,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path('/data0/hmpark/gpu_tt_portability_20261021')
DISPLAY_NAMES={'/usr/lib/xorg/Xorg','/usr/bin/gnome-shell'}

def snapshot():
    text=subprocess.check_output(['nvidia-smi'],text=True)
    xml=subprocess.check_output(['nvidia-smi','-q','-x'],text=True)
    tree=ET.fromstring(xml)
    permission=ROOT/'display-permission.json'
    policy=json.loads(permission.read_text()) if permission.exists() else {}
    allow=policy.get('approved_by_user') is True
    devices=[];busy=[]
    for gpu in tree.findall('gpu'):
        processes=[]
        for p in gpu.findall('./processes/process_info'):
            pid=p.findtext('pid')
            owner_result=subprocess.run(['ps','-p',pid,'-o','user='],capture_output=True,text=True)
            # Process may exit between nvidia-smi and ps; keep it busy until next snapshot.
            owner=owner_result.stdout.strip() if owner_result.returncode==0 else ''
            owner=owner or '<exited_or_unresolved>'
            process=dict(pid=int(pid),user=owner,type=p.findtext('type'),name=p.findtext('process_name'),used_memory=p.findtext('used_memory'))
            process['allowed_display']=allow and owner=='gdm' and process['type']=='G' and process['name'] in DISPLAY_NAMES
            processes.append(process)
            if not process['allowed_display']:busy.append(process)
        memory=gpu.find('fb_memory_usage')
        devices.append(dict(id=gpu.get('id'),uuid=gpu.findtext('uuid'),name=gpu.findtext('product_name'),
            memory={c.tag:c.text for c in memory} if memory is not None else {},processes=processes))
    assert devices,'nvidia-smi returned no GPU'
    return text,xml,dict(captured_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        devices=devices,busy=busy,display_permission=policy,
        measurement_condition='디스플레이 프로세스가 상주한 상태에서 측정')

def wait_idle(save,dst=None):
    while True:
        text,xml,data=snapshot()
        if not data['busy']:
            if dst is not None:
                (dst/'nvidia-smi-before.txt').write_text(text)
                (dst/'nvidia-smi-before.xml').write_text(xml)
                (dst/'gpu-state-before.json').write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
            return data
        save('waiting_for_GPU_processes',dict(processes=data['busy'],cell=str(dst) if dst else None))
        time.sleep(30)
