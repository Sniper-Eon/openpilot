"""Release check: retain the approved navigation STL bytes and verify CV imports.

This symbol check is necessary, not a substitute for real Android runtime tests.
Requires pyelftools on the build host; does not run native code.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile
from elftools.elf.elffile import ELFFile


def symbols(blob,defined):
  elf=ELFFile(io.BytesIO(blob));table=elf.get_section_by_name('.dynsym')
  return {symbol.name for symbol in table.iter_symbols()
          if symbol.name and (symbol['st_shndx']!='SHN_UNDEF')==defined}


def main():
  p=argparse.ArgumentParser();p.add_argument('--baseline-apk',type=Path,required=True)
  p.add_argument('--candidate-apk',type=Path,required=True);p.add_argument('--opencv-aar',type=Path,required=True)
  p.add_argument('--output',type=Path,required=True);a=p.parse_args();rows=[]
  with zipfile.ZipFile(a.baseline_apk) as old,zipfile.ZipFile(a.candidate_apk) as new,zipfile.ZipFile(a.opencv_aar) as original:
    for name in old.namelist():
      if name.endswith('/libc++_shared.so'):
        assert old.read(name)==new.read(name),'navigation runtime changed: '+name
    for name in new.namelist():
      if not name.endswith('/libopencv_java4.so'):continue
      abi=name.split('/')[1];stl='lib/'+abi+'/libc++_shared.so'
      original_stl=original.read('jni/'+abi+'/libc++_shared.so')
      required=symbols(new.read(name),False)&symbols(original_stl,True)
      provided=symbols(new.read(stl),True);missing=sorted(required-provided)
      row=dict(abi=abi,required_stl_symbols=len(required),missing=missing,
               navigation_runtime_preserved=new.read(stl)==old.read(stl),
               packaged_stl_sha256=hashlib.sha256(new.read(stl)).hexdigest());rows.append(row)
      assert not missing,missing
    assert rows,'no native stereo matcher packaged'
    model='assets/side_vehicle320.onnx';assert old.read(model)==new.read(model),'model changed during transport work'
  result=dict(passed=True,abis=rows,model_preserved=True,scope='static symbol/byte audit only, not a real-device compatibility test')
  a.output.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
