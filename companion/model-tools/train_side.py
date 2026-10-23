import json, os, random, yaml
from ultralytics import YOLO
random.seed(0)
D=os.path.abspath(os.environ.get('C3_TRAINING_OUTPUT', 'side_dataset'))
def split(tag):
    meta=json.load(open(f'{D}/meta_{tag}.json'))
    groups=sorted({m['src'] for m in meta}); random.shuffle(groups)
    val=set(groups[:max(1,len(groups)//5)])
    tr=[f"{D}/images/{tag}/{m['name']}.jpg" for m in meta if m['src'] not in val]
    va=[f"{D}/images/{tag}/{m['name']}.jpg" for m in meta if m['src'] in val]
    return tr,va
trn,van=split('night'); trd,vad=split('day')
open(f'{D}/train.txt','w').write('\n'.join(trn+trd))
open(f'{D}/val.txt','w').write('\n'.join(van+vad))
yaml.safe_dump({'path':D,'train':f'{D}/train.txt','val':f'{D}/val.txt','names':{0:'vehicle'}},open(f'{D}/data.yaml','w'))
print('train',len(trn)+len(trd),'val',len(van)+len(vad),flush=True)
try:
    m=YOLO('yolov8n.pt')
    m.train(data=f'{D}/data.yaml',epochs=30,imgsz=640,batch=16,device='mps',workers=4,project=os.environ.get('C3_TRAINING_RUNS', 'runs'),name='n1',exist_ok=True,patience=10)
except Exception as e:
    print('mps failed, cpu',e,flush=True)
    m=YOLO('yolov8n.pt')
    m.train(data=f'{D}/data.yaml',epochs=30,imgsz=640,batch=16,device='cpu',workers=4,project=os.environ.get('C3_TRAINING_RUNS', 'runs'),name='n1',exist_ok=True,patience=10)
print('TRAIN_DONE',flush=True)
