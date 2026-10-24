"""Offline calibrated stereo reference. No guessed baseline, no actuator output.

Vehicle bounding-box centers are never treated as stereo point correspondences.
Actual matched image features and a validated metric calibration are required.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


@dataclass
class Camera:
  size: tuple
  k: np.ndarray
  distortion: np.ndarray
  model: str

  @classmethod
  def load(cls, data):
    size=tuple(data['size']);k=np.asarray(data['K'],float).reshape(3,3);d=np.asarray(data['D'],float)
    model=data['model']
    if (len(size)!=2 or any(type(v) is not int or not 200<=v<=4096 for v in size) or
        not np.isfinite(k).all() or not np.isfinite(d).all() or
        k[0,0]<=0 or k[1,1]<=0 or not np.allclose(k[2],[0,0,1]) or
        not 0<=k[0,2]<=size[0] or not 0<=k[1,2]<=size[1] or abs(k[0,1])>1e-6 or
        model not in ('radtan','fisheye') or
        len(d)!=(4 if model=='fisheye' else 5)):
      raise ValueError('invalid_camera_calibration')
    return cls(size,k,d,model)

  def matrix(self, size):
    w,h=size
    if w<=0 or h<=0 or abs((w/h)/(self.size[0]/self.size[1])-1)>.005:
      raise ValueError('camera_crop_or_aspect_changed')
    k=self.k.copy();k[0]*=w/self.size[0];k[1]*=h/self.size[1]
    return k

  def rays(self, pixels, size):
    p=np.asarray(pixels,float).reshape(-1,1,2)
    if not np.isfinite(p).all():raise ValueError('nonfinite_feature')
    k=self.matrix(size)
    normalized=(cv2.fisheye.undistortPoints(p,k,self.distortion) if self.model=='fisheye'
                else cv2.undistortPoints(p,k,self.distortion))
    return normalized.reshape(-1,2)


class StereoCalibration:
  def __init__(self, data):
    if (data.get('version')!=1 or data.get('validated') is not True or data.get('units')!='metres' or
        not isinstance(data.get('device_id'),str) or not data['device_id'] or
        data.get('calibration_pairs',0)<15 or data.get('validation_pairs',0)<5):
      raise ValueError('metric_calibration_not_validated')
    for key in ('stereo_rms_px','heldout_rms_px'):
      value=data.get(key)
      if type(value) not in (float,int) or not np.isfinite(value) or not 0<=value<=1:
        raise ValueError('calibration_quality_insufficient')
    self.wide=Camera.load(data['wide']);self.narrow=Camera.load(data['narrow'])
    profiles=data.get('profile_ids')
    if not isinstance(profiles,list) or len(profiles)!=2 or any(not isinstance(p,str) or not p for p in profiles) or profiles[0]==profiles[1]:
      raise ValueError('missing_distinct_camera_profiles')
    self.profile_ids=tuple(profiles)
    self.r=np.asarray(data['R_narrow_from_wide'],float).reshape(3,3)
    self.t=np.asarray(data['t_narrow_from_wide_m'],float).reshape(3,1)
    if (not np.isfinite(self.r).all() or not np.isfinite(self.t).all() or
        not np.allclose(self.r.T@self.r,np.eye(3),atol=1e-4) or
        abs(np.linalg.det(self.r)-1)>1e-4 or not .01<=np.linalg.norm(self.t)<=.5):
      raise ValueError('invalid_metric_extrinsics')
    self.device_id=data['device_id'];self.id=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

  @classmethod
  def load(cls,path):
    return cls(json.loads(Path(path).read_text()))


def triangulate(cal, wide_pixels, narrow_pixels, wide_size, narrow_size, skew_ns=0,
                pixel_error_px=1.0, relative_motion_bound_mps=40.0):
  """Return camera-coordinate points and conservative sensitivity bounds.

  Temporal skew adds a worst-case motion/baseline term. Geometry passing this
  check is still experimental; it is not an empirical distance-accuracy claim.
  """
  wp=np.asarray(wide_pixels,float).reshape(-1,2);npix=np.asarray(narrow_pixels,float).reshape(-1,2)
  if (len(wp)!=len(npix) or type(skew_ns) is not int or abs(skew_ns)>5_000_000 or
      not np.isfinite(pixel_error_px) or pixel_error_px<.5 or
      not np.isfinite(relative_motion_bound_mps) or relative_motion_bound_mps<0):
    raise ValueError('invalid_correspondence_or_timing')
  if not len(wp):return []
  for points,size in ((wp,wide_size),(npix,narrow_size)):
    if not np.isfinite(points).all() or (points<0).any() or (points[:,0]>=size[0]).any() or (points[:,1]>=size[1]).any():
      raise ValueError('feature_outside_image')
  kw=cal.wide.matrix(wide_size);kn=cal.narrow.matrix(narrow_size)
  a=cal.wide.rays(wp,wide_size);b=cal.narrow.rays(npix,narrow_size)
  tx=np.array([[0,-cal.t[2,0],cal.t[1,0]],[cal.t[2,0],0,-cal.t[0,0]],[-cal.t[1,0],cal.t[0,0],0]])
  e=tx@cal.r;p1=np.column_stack((np.eye(3),np.zeros(3)));p2=np.column_stack((cal.r,cal.t))
  def solve(x,y):
    h=cv2.triangulatePoints(p1,p2,x.T,y.T)
    with np.errstate(divide='ignore',invalid='ignore'):return (h[:3]/h[3]).T
  xyz=solve(a,b);bounds=np.zeros(len(a))
  # Match-localization perturbations in both image axes and both cameras.
  for camera in ('wide','narrow'):
    for axis in (0,1):
      for sign in (-1,1):
        x,y=wp.copy(),npix.copy();(x if camera=='wide' else y)[:,axis]+=sign*pixel_error_px
        shifted=solve(cal.wide.rays(x,wide_size),cal.narrow.rays(y,narrow_size))
        delta=np.abs(shifted[:,2]-xyz[:,2]);delta[~np.isfinite(delta)]=np.inf
        delta[shifted[:,2]<=0]=np.inf;bounds=np.maximum(bounds,delta)
  temporal_fraction=relative_motion_bound_mps*abs(skew_ns)/1e9/np.linalg.norm(cal.t)
  bounds+=np.abs(xyz[:,2])*temporal_fraction
  rows=[]
  for i,(point,x,y) in enumerate(zip(xyz,a,b)):
    aw=np.r_[x,1.];bn=np.r_[y,1.];ln=e@aw;lw=e.T@bn
    residual=abs(bn@ln)
    epipolar=max(residual/max(1e-15,np.linalg.norm(ln[:2]))*min(kn[0,0],kn[1,1]),
                 residual/max(1e-15,np.linalg.norm(lw[:2]))*min(kw[0,0],kw[1,1]))
    narrow=cal.r@point+cal.t[:,0]
    valid=(np.isfinite(point).all() and 2<=point[2]<=80 and narrow[2]>0 and
           epipolar<=1.5 and bounds[i]<=max(.25,.2*point[2]))
    rows.append(dict(valid=bool(valid),xyz_wide_camera_m=point.tolist() if valid else None,
                     depth_wide_m=float(point[2]) if valid else None,
                     sensitivity_bound_m=float(bounds[i]) if np.isfinite(bounds[i]) else None,
                     epipolar_error_px=float(epipolar),control_eligible=False,clearance_authorized=False))
  return rows


def match_vehicle_features(cal, wide_image, narrow_image, wide_boxes, narrow_boxes, skew_ns, device_id, profile_ids):
  """SIFT correspondences within vehicle detections, ratio + mutual + epipolar gates."""
  if device_id!=cal.device_id:raise ValueError('calibration_for_different_device')
  if tuple(profile_ids)!=cal.profile_ids:raise ValueError('camera_profile_or_order_changed')
  if len(wide_boxes)>64 or len(narrow_boxes)>64:raise ValueError('too_many_boxes')
  images=[wide_image,narrow_image];boxes=[wide_boxes,narrow_boxes];keypoints=[];descriptors=[]
  for image,bs in zip(images,boxes):
    if image is None or image.ndim not in (2,3):raise ValueError('invalid_image')
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    mask=np.zeros(gray.shape,np.uint8)
    for x1,y1,x2,y2,*_ in bs:
      x1,x2=sorted([max(0,min(gray.shape[1],int(x1))),max(0,min(gray.shape[1],int(x2)))])
      y1,y2=sorted([max(0,min(gray.shape[0],int(y1))),max(0,min(gray.shape[0],int(y2)))])
      mask[y1:y2,x1:x2]=255
    kp,desc=cv2.SIFT_create(nfeatures=1200).detectAndCompute(gray,mask)
    keypoints.append(kp);descriptors.append(desc)
  if any(d is None or len(d)<2 for d in descriptors):return []
  bf=cv2.BFMatcher(cv2.NORM_L2);reverse=bf.match(descriptors[1],descriptors[0]);back={m.queryIdx:m.trainIdx for m in reverse}
  matches=[p[0] for p in bf.knnMatch(*descriptors,k=2) if len(p)==2 and p[0].distance<.7*p[1].distance and back.get(p[0].trainIdx)==p[0].queryIdx]
  if not matches:return []
  wp=[keypoints[0][m.queryIdx].pt for m in matches];npix=[keypoints[1][m.trainIdx].pt for m in matches]
  measurements=triangulate(cal,wp,npix,(wide_image.shape[1],wide_image.shape[0]),(narrow_image.shape[1],narrow_image.shape[0]),skew_ns)
  def containing(bs,p):return [i for i,b in enumerate(bs) if b[0]<=p[0]<=b[2] and b[1]<=p[1]<=b[3]]
  groups={}
  for p,q,measurement in zip(wp,npix,measurements):
    a,b=containing(wide_boxes,p),containing(narrow_boxes,q)
    if measurement['valid'] and len(a)==len(b)==1:groups.setdefault((a[0],b[0]),[]).append(measurement)
  rows=[]
  for (i,j),points in groups.items():
    if len(points)<8:continue
    depths=np.array([p['depth_wide_m'] for p in points]);depth=float(np.median(depths))
    if np.percentile(depths,75)-np.percentile(depths,25)>max(.5,depth*.2):continue
    if sum(k[0]==i for k in groups)>1 or sum(k[1]==j for k in groups)>1:continue
    rows.append(dict(wide_index=i,narrow_index=j,depth_wide_m=depth,matched_features=len(points),
                     source='calibrated_feature_stereo_offline',calibration_id=cal.id,
                     control_eligible=False,clearance_authorized=False))
  return rows
