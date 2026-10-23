"""Independent read-only observer process; no imports from lane-change control."""
import argparse,json,os,time
from pathlib import Path
from openpilot.sunnypilot.navassist.closing_risk import ClosingRiskObserver

def read_packet(path):
    try:
        with path.open() as f:raw=f.read(16385)
        if len(raw)>16384:return None
        return json.loads(raw)
    except (OSError,ValueError,RecursionError):return None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=Path('/dev/shm/phone_side_vehicles.json'))
    parser.add_argument('--output',type=Path,default=Path('/dev/shm/phone_closing_risk.json'))
    parser.add_argument('--once',action='store_true');args=parser.parse_args()
    if args.input.resolve()==args.output.resolve():parser.error('input and output must differ')
    observer=ClosingRiskObserver();args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_name('.'+args.output.name+'.'+str(os.getpid())+'.tmp')
    try:
        while True:
            now=time.monotonic_ns();result=observer.update(read_packet(args.input),now)
            result={**result,'checked_mono_ns':now}
            with temp.open('w') as f:json.dump(result,f,allow_nan=False)
            os.replace(temp,args.output)
            if args.once:return
            time.sleep(.1)
    finally:
        temp.unlink(missing_ok=True)

if __name__=='__main__':main()
