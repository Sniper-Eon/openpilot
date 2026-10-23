import base64, glob, json, os, zlib
import numpy as np
from PIL import Image
from ultralytics import YOLO

W=os.environ['C3_DATA_ROOT']
OUT=os.path.abspath(os.environ.get('C3_TRAINING_OUTPUT', 'side_dataset'))
os.makedirs(f'{OUT}/images/night',exist_ok=True); os.makedirs(f'{OUT}/labels/night',exist_ok=True)
os.makedirs(f'{OUT}/images/day',exist_ok=True); os.makedirs(f'{OUT}/labels/day',exist_ok=True)
yolo=YOLO('yolov8m.pt')
VEH={'car','truck','bus','motorcycle'}

def decode(d):
    img=d['image']; w,h=img['width'],img['height']; raw=zlib.decompress(base64.b64decode(img['nv12_zlib']))
    y=np.frombuffer(raw[:w*h],dtype=np.uint8).reshape(h,w).astype(np.float32)
    uv=np.frombuffer(raw[w*h:w*h*3//2],dtype=np.uint8).reshape(h//2,w//2,2).astype(np.float32)
    u=np.repeat(np.repeat(uv[:,:,0],2,0),2,1); v=np.repeat(np.repeat(uv[:,:,1],2,0),2,1)
    rgb=np.stack([y+1.402*(v-128),y-0.344136*(u-128)-0.714136*(v-128),y+1.772*(u-128)],-1).clip(0,255).astype(np.uint8)
    return rgb

def process(paths, tag, step):
    meta=[]; n=0
    for fp in paths:
        with open(fp) as f:
            for i,line in enumerate(f):
                if i%step: continue
                d=json.loads(line); rgb=decode(d)
                name=f'{tag}-{os.path.basename(fp).split(".")[0]}-{i:05d}'
                Image.fromarray(rgb).save(f'{OUT}/images/{tag}/{name}.jpg',quality=90)
                res=yolo(Image.fromarray(rgb),imgsz=640,conf=0.2,verbose=False)[0]
                lines=[]
                for b in res.boxes:
                    if res.names[int(b.cls[0])] not in VEH: continue
                    x1,y1,x2,y2=[float(v) for v in b.xyxy[0]]; w=640; h=400
                    cx=((x1+x2)/2)/w; cy=((y1+y2)/2)/h; bw=(x2-x1)/w; bh=(y2-y1)/h
                    if bw<=0 or bh<=0: continue
                    lines.append(f'0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}')
                open(f'{OUT}/labels/{tag}/{name}.txt','w').write('\n'.join(lines))
                meta.append({'name':name,'src':fp,'idx':i,'labels':len(lines)})
                n+=1
                if n%100==0: print(tag,n,'done',flush=True)
    with open(f'{OUT}/meta_{tag}.json','w') as f: json.dump(meta,f)

night=sorted(glob.glob(f'{W}/highway-capture-20261017-0c9ef729/frames/frames-*.jsonl'))
day=sorted(glob.glob(f'{W}/road-review-20261017-afternoon/frames/wide-*.jsonl'))
print('night files',len(night),'day files',len(day),flush=True)
process(night,'night',5)
process(day,'day',2)
print('DONE',flush=True)
