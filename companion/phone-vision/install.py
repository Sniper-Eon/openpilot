#!/usr/bin/env python3
"""Install the standalone bridge; never change the openpilot branch or enable control."""
from pathlib import Path
import argparse,datetime,hashlib,json,os,pwd,secrets,shutil

FILES=('phone_vision_bridge.py','dual_camera_store.py','start_bridge.sh','ensure_bridge.sh','phone-vision-bridge.service')
def install(source:Path,target:Path,legacy_roi:Path|None=None):
 target.mkdir(parents=True,exist_ok=True)
 token=target/'connection-code'
 reused=token.exists()
 if token.exists() and len(token.read_text().strip())<32:raise ValueError('Existing connection code is invalid; preserve it and repair explicitly.')
 snapshot={}
 for name in FILES:
  p=target/name
  if p.exists():snapshot[name]=hashlib.sha256(p.read_bytes()).hexdigest()
 if snapshot:
  backup=target/'backups'/datetime.datetime.now().strftime('install-%Y%m%d-%H%M%S-%f');backup.mkdir(parents=True)
  for name in snapshot:shutil.copy2(target/name,backup/name)
  (backup/'manifest.json').write_text(json.dumps(snapshot,indent=2))
 for name in FILES:
  p=target/name;tmp=target/(name+'.install-tmp');shutil.copy2(source/name,tmp);tmp.chmod(0o755 if name.endswith('.sh') else 0o644);os.replace(tmp,p)
 if not token.exists():
  fd=os.open(token,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w') as out:out.write(secrets.token_urlsafe(32)+'\n')
  if os.geteuid()==0:
   try:
    comma=pwd.getpwnam('comma');os.chown(token,comma.pw_uid,comma.pw_gid)
   except KeyError:pass
 roi=target/'roi.json'
 if not roi.exists():shutil.copy2(legacy_roi if legacy_roi and legacy_roi.is_file() else source/'roi.example.json',roi)
 config=target/'blindspot-assist.json'
 if not config.exists():config.write_text(json.dumps({'version':1,'mode':'shadow'})+'\n')
 return {'installed_files':list(FILES),'connection_code_path':str(token),'connection_code_reused':reused,'boot_entry_modified':False,'services_started':False}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,default=Path('/data/phone-vision'));a=p.parse_args()
 print(json.dumps(install(Path(__file__).resolve().parent/'c3',a.directory,Path('/data/wide-capture/roi.json')),indent=2))
 print('Start only while parked: /data/phone-vision/ensure_bridge.sh')
 print('Read this device connection code locally: cat /data/phone-vision/connection-code')
if __name__=='__main__':main()
