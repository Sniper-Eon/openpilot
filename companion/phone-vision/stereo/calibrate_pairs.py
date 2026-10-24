"""Checkerboard metric calibration with separate heldout validation pairs.

Run on Mac. Requires measured square size and varied paired board views.
The board must be stationary within each pair; no moving-road auto-calibration.
"""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from stereo_geometry import Camera,StereoCalibration


def fit_camera(objects,points,size,model):
  if model=='fisheye':
    _,k,d,_,_=cv2.fisheye.calibrate([x.astype(float).reshape(1,-1,3) for x in objects],
        [x.astype(float).reshape(1,-1,2) for x in points],size,None,None,
        flags=cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC|cv2.fisheye.CALIB_CHECK_COND|cv2.fisheye.CALIB_FIX_SKEW)
  else:
    _,k,d,_,_=cv2.calibrateCamera(objects,points,size,None,None)
    d=d.reshape(-1)[:5]
  return Camera(size,k,d.reshape(-1),model)


def project(camera,obj,rvec,tvec):
  if camera.model=='fisheye':
    return cv2.fisheye.projectPoints(obj.astype(float).reshape(-1,1,3),rvec,tvec,camera.k,camera.distortion)[0].reshape(-1,2)
  return cv2.projectPoints(obj,rvec,tvec,camera.k,camera.distortion)[0].reshape(-1,2)


def board_errors(rows,cw,cn,r,t):
  errors=[]
  for obj,w,n in rows:
    rays=cw.rays(w,cw.size).astype(float)
    ok,rv,tv=cv2.solvePnP(obj,rays,np.eye(3),np.zeros(5))
    if not ok:raise ValueError('heldout_pose_failed')
    rw=cv2.Rodrigues(rv)[0];rn=cv2.Rodrigues(r@rw)[0];tn=r@tv+t
    errors.extend(np.sum((project(cw,obj,rv,tv)-w.reshape(-1,2))**2,axis=1))
    errors.extend(np.sum((project(cn,obj,rn,tn)-n.reshape(-1,2))**2,axis=1))
  return float(np.sqrt(np.mean(errors)))


def main():
  p=argparse.ArgumentParser();p.add_argument('pairs',type=Path)
  p.add_argument('--columns',type=int,required=True);p.add_argument('--rows',type=int,required=True)
  p.add_argument('--square-metres',type=float,required=True)
  p.add_argument('--wide-model',choices=['fisheye','radtan'],default='fisheye')
  p.add_argument('--narrow-model',choices=['fisheye','radtan'],default='radtan')
  p.add_argument('--output',type=Path,required=True);a=p.parse_args()
  if not (3<=a.columns<=20 and 3<=a.rows<=20 and .005<=a.square_metres<=.2):p.error('invalid measured board geometry')
  if a.output.exists():p.error('refusing to overwrite calibration')
  obj=np.zeros((a.columns*a.rows,3),np.float32);obj[:,:2]=np.mgrid[0:a.columns,0:a.rows].T.reshape(-1,2)*a.square_metres
  rows=[];sizes={};device=None;profiles=None
  for path in sorted(a.pairs.glob('*.json')):
    data=json.loads(path.read_text())
    if data.get('version')!=2:continue
    w,n=data['wide'],data['narrow']
    if not w.get('device_id') or w['device_id']!=n.get('device_id'):raise ValueError('missing_or_mixed_device_identity')
    current=(w.get('calibration_id'),n.get('calibration_id'))
    if any(not isinstance(profile,str) or not profile for profile in current):continue
    if device is None:device=w['device_id'];profiles=current
    if w['device_id']!=device or current!=profiles:raise ValueError('camera_profile_changed')
    points=[]
    for name in ('wide','narrow'):
      frame=data[name];image_path=(a.pairs/frame['image_file']).resolve()
      if image_path.parent!=a.pairs.resolve():raise ValueError('image_path_outside_dataset')
      image=cv2.imread(str(image_path),0)
      if image is None:raise ValueError('missing_image')
      size=(image.shape[1],image.shape[0])
      if name in sizes and size!=sizes[name]:raise ValueError('camera_size_changed')
      sizes[name]=size
      ok,corners=cv2.findChessboardCornersSB(image,(a.columns,a.rows),flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
      if not ok:break
      points.append(corners.astype(np.float32))
    if len(points)==2:rows.append((obj.copy(),*points))
  if len(rows)<20:raise ValueError('need_20_or_more_paired_board_views_with_varied_positions')
  # Fixed split before fitting. Every fourth usable view is held out.
  train=[row for i,row in enumerate(rows) if i%4!=0];validation=[row for i,row in enumerate(rows) if i%4==0]
  if len(train)<15 or len(validation)<5:raise ValueError('insufficient_train_or_validation_views')
  for side in (1,2):
    centres=np.array([row[side].reshape(-1,2).mean(axis=0) for row in train]);size=np.array(sizes['wide' if side==1 else 'narrow'])
    if (np.ptp(centres,axis=0)/size < .15).any():raise ValueError('board_positions_not_varied_enough')
  objects=[row[0] for row in train]
  cw=fit_camera(objects,[row[1] for row in train],sizes['wide'],a.wide_model)
  cn=fit_camera(objects,[row[2] for row in train],sizes['narrow'],a.narrow_model)
  wp=[cw.rays(row[1],cw.size).reshape(-1,1,2).astype(np.float32) for row in train]
  npix=[cn.rays(row[2],cn.size).reshape(-1,1,2).astype(np.float32) for row in train]
  _,_,_,_,_,r,t,_,_=cv2.stereoCalibrate(objects,wp,npix,np.eye(3),np.zeros(5),np.eye(3),np.zeros(5),(1,1),flags=cv2.CALIB_FIX_INTRINSIC)
  def camera_dict(c):return dict(size=list(c.size),K=c.k.tolist(),D=c.distortion.tolist(),model=c.model)
  result=dict(version=1,validated=False,units='metres',device_id=device,profile_ids=list(profiles),
              calibration_pairs=len(train),validation_pairs=len(validation),
              stereo_rms_px=board_errors(train,cw,cn,r,t),heldout_rms_px=board_errors(validation,cw,cn,r,t),
              wide=camera_dict(cw),narrow=camera_dict(cn),R_narrow_from_wide=r.tolist(),t_narrow_from_wide_m=t[:,0].tolist(),
              board=dict(columns=a.columns,rows=a.rows,square_metres=a.square_metres),purpose='experimental_offline_stereo_only')
  try:
    StereoCalibration(dict(result,validated=True));result['validated']=True
  finally:
    a.output.write_text(json.dumps(result,indent=2))
  print('Calibration quality gates passed; still requires independent range/speed validation.')


if __name__=='__main__':main()
