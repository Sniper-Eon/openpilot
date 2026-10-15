"""Download the upstream YOLOPv2 TorchScript release with a pinned byte digest."""
import argparse
import hashlib
import os
from pathlib import Path
import urllib.request

URL = 'https://github.com/CAIC-AD/YOLOPv2/releases/download/V0.0.1/yolopv2.pt'
SHA256 = 'f2a8c8374203ae3e67ff9c184e931f763957de92a993b23269e4e721627f1f8c'
SIZE = 156380200


def verify(path: Path) -> bool:
  if not path.is_file() or path.stat().st_size != SIZE:return False
  digest=hashlib.sha256()
  with path.open('rb') as f:
    while chunk:=f.read(1024*1024):digest.update(chunk)
  return digest.hexdigest()==SHA256


def main():
  parser=argparse.ArgumentParser(description=__doc__)
  parser.add_argument('destination',type=Path)
  path=parser.parse_args().destination
  if verify(path):return
  path.parent.mkdir(parents=True,exist_ok=True)
  temporary=path.with_suffix('.part')
  try:
    size=0
    with urllib.request.urlopen(URL,timeout=60) as response,temporary.open('wb') as out:
      while chunk:=response.read(1024*1024):
        size+=len(chunk)
        if size>SIZE:raise ValueError('model is larger than pinned release')
        out.write(chunk)
    if not verify(temporary):raise ValueError('model digest mismatch')
    os.replace(temporary,path)
  finally:
    temporary.unlink(missing_ok=True)


if __name__=='__main__':main()
