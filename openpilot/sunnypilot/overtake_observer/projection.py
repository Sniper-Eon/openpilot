"""Experimental box-foot/ground-plane intersection; never validated range output."""
import math
import numpy as np

def project_box(box, camera_from_calib, height_m, native_size, payload_size=(640,400), *, geometry_valid=False):
  unknown=lambda reason:{'candidate_forward_m':None,'candidate_right_m':None,'valid_for_control':False,'reason':reason}
  if geometry_valid is not True:return unknown('geometry_unconfirmed')
  try:
    x1,y1,x2,y2=map(float,box);nw,nh=map(float,native_size);pw,ph=map(float,payload_size)
    if not all(math.isfinite(v) for v in (x1,y1,x2,y2,nw,nh,pw,ph,height_m)) or min(nw,nh,pw,ph)<=0 or not .5<=height_m<=3:
      return unknown('invalid_dimensions_or_height')
    u=(x1+x2)/2;v=y2
    if x2-x1<8 or y2-y1<8 or not .1*pw<=u<=.9*pw or v>=.75*ph or x1<=1 or x2>=pw-1:
      return unknown('box_contact_unreliable')
    matrix=np.asarray(camera_from_calib,dtype=float)
    if matrix.shape!=(3,3) or not np.all(np.isfinite(matrix)):return unknown('invalid_camera_matrix')
    h=np.column_stack((matrix[:,:2],matrix[:,2]*height_m));inv=np.linalg.inv(h);values=[]
    for yy in (v,v-2,v+2):
      q=inv@np.array([u/pw*nw,yy/ph*nh,1.])
      if q[2]<=1e-6:return unknown('horizon_or_behind')
      xx,right=q[:2]/q[2]
      if not 2<=xx<=80:return unknown('distance_outside_model_window')
      values.append((float(xx),float(right)))
    if max(x[0] for x in values)-min(x[0] for x in values)>15:return unknown('projection_sensitive')
    return {'candidate_forward_m':values[0][0],'candidate_right_m':values[0][1],
            'pixel_perturbation_forward_span_m':max(x[0] for x in values)-min(x[0] for x in values),
            'valid_for_control':False,'reason':'experimental_raw_wide_ground_plane',
            'contact_verified':False,'distortion_verified':False}
  except (ValueError,TypeError,np.linalg.LinAlgError):return unknown('invalid_projection_input')
