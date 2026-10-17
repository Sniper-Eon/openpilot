"""Offline image association and explicitly experimental metric motion.
Not a vehicle controller. Unknown calibration/identity never yields valid speed.
"""
import math
from collections import deque
import numpy as np
def linear_sum_assignment(cost):
    """Minimum-cost assignment with dummy padding; no extra runtime dependency."""
    rows,cols=cost.shape;n=max(rows,cols)
    matrix=np.full((n,n),1e6);matrix[:rows,:cols]=cost
    u=[0.]*(n+1);v=[0.]*(n+1);p=[0]*(n+1);way=[0]*(n+1)
    for i in range(1,n+1):
        p[0]=i;j0=0;mins=[float('inf')]*(n+1);used=[False]*(n+1)
        while True:
            used[j0]=True;i0=p[j0];delta=float('inf');j1=0
            for j in range(1,n+1):
                if used[j]:continue
                cur=matrix[i0-1,j-1]-u[i0]-v[j]
                if cur<mins[j]:mins[j]=cur;way[j]=j0
                if mins[j]<delta:delta=mins[j];j1=j
            for j in range(n+1):
                if used[j]:u[p[j]]+=delta;v[j]-=delta
                else:mins[j]-=delta
            j0=j1
            if p[j0]==0:break
        while True:
            j1=way[j0];p[j0]=p[j1];j0=j1
            if j0==0:break
    pairs=[(p[j]-1,j-1) for j in range(1,n+1) if p[j]<=rows and j<=cols]
    return [a for a,b in pairs],[b for a,b in pairs]

def iou(a,b):
 x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]));s=x*y
 return s/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-s)

def velocity(history):
 if not history or history[-1].get('ground_candidate') is None:
  return {'state':'unknown','reason':'current_ground_estimate_missing','candidate_relative_forward_mps':None}
 rows=[r for r in history if r.get('ground_candidate') is not None]
 if len(rows)<3:return {'state':'unknown','reason':'need_three_metric_samples','candidate_relative_forward_mps':None}
 rows=rows[-5:];ts=np.array([(r['mono_ns']-rows[0]['mono_ns'])/1e9 for r in rows]);xs=np.array([r['ground_candidate'][0] for r in rows])
 if np.any(np.diff(ts)<=0) or ts[-1]<.3:return {'state':'unknown','reason':'invalid_time_span','candidate_relative_forward_mps':None}
 slope,intercept=np.polyfit(ts,xs,1);res=float(np.sqrt(np.mean((xs-(slope*ts+intercept))**2)))
 if abs(slope)>60 or res>3:return {'state':'unknown','reason':'motion_fit_inconsistent','candidate_relative_forward_mps':None}
 return {'state':'experimental','candidate_relative_forward_mps':float(slope),'positive_means':'moving_away_along_current_camera_forward_axis','fit_rmse_m':res,'samples':len(rows),'span_s':float(ts[-1]),'valid_for_control':False,'limitations':['unverified_ground_contact','raw_wide_camera_geometry_unvalidated','ego_rotation_not_compensated']}

class Tracker:
 def __init__(self,max_gap_s=1.5):
  self.max_gap_ns=int(max_gap_s*1e9);self.tracks={};self.counter=0;self.route=None;self.last=None
 def update(self,route,mono_ns,detections):
  if type(mono_ns) is not int:raise ValueError('integer capture time required')
  if route!=self.route:
   self.tracks={};self.route=route;self.last=None
  if self.last is not None and mono_ns<=self.last:raise ValueError('duplicate/backward frame')
  self.last=mono_ns
  self.tracks={k:v for k,v in self.tracks.items() if mono_ns-v['mono_ns']<=self.max_gap_ns}
  keys=list(self.tracks);cost=np.full((len(keys),len(detections)),1e6)
  for i,k in enumerate(keys):
   t=self.tracks[k];a=t['bbox_xyxy']
   for j,d in enumerate(detections):
    b=d['bbox_xyxy']
    if t['class_id_raw']!=d['class_id_raw']:continue
    ratio=(b[2]-b[0])*(b[3]-b[1])/max(1,(a[2]-a[0])*(a[3]-a[1]))
    center=math.hypot((a[0]+a[2]-b[0]-b[2])/1280,(a[1]+a[3]-b[1]-b[3])/800)
    if not .25<=ratio<=4 or center>.18:continue
    overlap=iou(a,b)
    if overlap<.05 and center>.04:continue
    cost[i,j]=1-overlap+center
  # Ambiguous many-to-one/one-to-many links start fresh identities; do not guess.
  ambiguous_rows=set();ambiguous_cols=set()
  for i in range(len(keys)):
   v=np.sort(cost[i][cost[i]<1e5])
   if len(v)>1 and v[1]-v[0]<.12:ambiguous_rows.add(i)
  for j in range(len(detections)):
   v=np.sort(cost[:,j][cost[:,j]<1e5])
   if len(v)>1 and v[1]-v[0]<.12:ambiguous_cols.add(j)
  mapping={}
  if cost.size:
   ii,jj=linear_sum_assignment(cost)
   for i,j in zip(ii,jj):
    if cost[i,j]<1e5 and i not in ambiguous_rows and j not in ambiguous_cols:mapping[j]=keys[i]
  # Unmatched old identities expire immediately: no occlusion bridge/re-ID claims.
  current={};output=[]
  for j,d in enumerate(detections):
   linked=j in mapping
   if linked:k=mapping[j];history=self.tracks[k]['history']
   else:self.counter+=1;k=f'{route}-T{self.counter}';history=deque(maxlen=5)
   if d.get('ground_candidate') is None:history.clear()
   history.append({'mono_ns':mono_ns,'ground_candidate':d.get('ground_candidate')})
   current[k]={**d,'mono_ns':mono_ns,'history':history}
   output.append({**d,'track_id':k,'association':'image_candidate_link' if linked else 'new_identity','association_validated':False,'metric_motion':velocity(history),'distance_m':None,'relative_speed_mps':None,'valid_for_control':False})
  self.tracks=current
  return output
