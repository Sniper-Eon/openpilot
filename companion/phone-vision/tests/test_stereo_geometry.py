import copy
import cv2
import numpy as np
import pytest
from stereo_geometry import StereoCalibration,triangulate,match_vehicle_features
from calibrate_pairs import fit_camera,board_errors


def calibration(baseline=.3):
  # Entirely synthetic; this is NOT a measurement of C3 baseline or calibration.
  return dict(version=1,validated=True,units='metres',device_id='synthetic-test-device',
              profile_ids=['synthetic-wide','synthetic-narrow'],
              calibration_pairs=20,validation_pairs=5,stereo_rms_px=.1,heldout_rms_px=.2,
              wide=dict(size=[640,400],K=[[600,0,320],[0,600,200],[0,0,1]],D=[0]*5,model='radtan'),
              narrow=dict(size=[640,400],K=[[1200,0,320],[0,1200,200],[0,0,1]],D=[0]*5,model='radtan'),
              R_narrow_from_wide=np.eye(3).tolist(),t_narrow_from_wide_m=[-baseline,0,0])


def pixels(cal,points):
  a=(cal.wide.k@points.T).T;a=a[:,:2]/a[:,2:]
  xyz=(cal.r@points.T+cal.t).T;b=(cal.narrow.k@xyz.T).T;b=b[:,:2]/b[:,2:]
  return a,b


def test_true_metric_triangulation_with_different_focals():
  cal=StereoCalibration(calibration());xyz=np.array([[.3,.1,10],[.1,-.1,8.]])
  a,b=pixels(cal,xyz);rows=triangulate(cal,a,b,(640,400),(640,400))
  assert all(row['valid'] for row in rows)
  np.testing.assert_allclose([row['xyz_wide_camera_m'] for row in rows],xyz,atol=1e-6)
  assert all(row['control_eligible'] is False for row in rows)


@pytest.mark.parametrize('case',['missing_quality','wrong_units','zero_baseline','bad_rotation','too_few_heldout'])
def test_requires_real_validated_metric_calibration(case):
  data=calibration()
  if case=='missing_quality':data['validated']=False
  if case=='wrong_units':data['units']='millimetres'
  if case=='zero_baseline':data['t_narrow_from_wide_m']=[0,0,0]
  if case=='bad_rotation':data['R_narrow_from_wide'][0][0]=2
  if case=='too_few_heldout':data['validation_pairs']=0
  with pytest.raises(ValueError):StereoCalibration(data)


def test_short_baseline_and_timing_uncertainty_refuse_far_depth():
  cal=StereoCalibration(calibration(.06));a,b=pixels(cal,np.array([[0.,0.,40.]]))
  assert not triangulate(cal,a,b,(640,400),(640,400))[0]['valid']
  a,b=pixels(cal,np.array([[0.,0.,4.]]))
  assert not triangulate(cal,a,b,(640,400),(640,400),skew_ns=1_000_000)[0]['valid']
  with pytest.raises(ValueError):triangulate(cal,a,b,(640,400),(640,400),skew_ns=6_000_000)


def test_epipolar_wrong_points_and_resize():
  cal=StereoCalibration(calibration());xyz=np.array([[.3,.1,10.]])
  a,b=pixels(cal,xyz);b[0,1]+=10
  assert not triangulate(cal,a,b,(640,400),(640,400))[0]['valid']
  a,b=pixels(cal,xyz);rows=triangulate(cal,a/2,b/2,(320,200),(320,200))
  assert rows[0]['valid'];assert abs(rows[0]['depth_wide_m']-10)<1e-6
  with pytest.raises(ValueError):cal.wide.matrix((640,480))


def test_correspondence_uses_real_texture_features_not_box_centers():
  cal=StereoCalibration(calibration());rng=np.random.default_rng(20261024)
  image=np.zeros((400,640),np.uint8);image[150:250,270:370]=rng.integers(0,256,(100,100),np.uint8)
  image=cv2.GaussianBlur(image,(3,3),.5)
  narrow=cv2.warpAffine(image,np.array([[2.,0.,-356.],[0.,2.,-200.]]),(640,400))
  rows=match_vehicle_features(cal,image,narrow,[[270,150,370,250]],[[184,100,384,300]],0,'synthetic-test-device',cal.profile_ids)
  assert len(rows)==1 and rows[0]['matched_features']>=8
  assert abs(rows[0]['depth_wide_m']-10)<.1
  assert match_vehicle_features(cal,np.zeros_like(image),np.zeros_like(image),[[270,150,370,250]],[[184,100,384,300]],0,'synthetic-test-device',cal.profile_ids)==[]
  with pytest.raises(ValueError):match_vehicle_features(cal,image,narrow,[],[],0,'other-device',cal.profile_ids)
  with pytest.raises(ValueError):match_vehicle_features(cal,image,narrow,[],[],0,'synthetic-test-device',list(reversed(cal.profile_ids)))


def test_fisheye_inverse_against_known_projected_points():
  data=calibration();data['wide']['model']='fisheye';data['wide']['D']=[.01,-.002,.0001,0]
  cal=StereoCalibration(data);points=np.array([[.5,.3,4.],[-.8,-.4,5.],[0.,0.,3.]])
  pixels=cv2.fisheye.projectPoints(points.reshape(-1,1,3),np.zeros(3),np.zeros(3),cal.wide.k,cal.wide.distortion)[0]
  rays=cal.wide.rays(pixels,(640,400))
  np.testing.assert_allclose(rays,points[:,:2]/points[:,2:],atol=1e-7)


def test_calibration_recovers_known_intrinsics_and_checks_heldout_poses():
  cal=StereoCalibration(calibration());obj=np.zeros((54,3),np.float32);obj[:,:2]=np.mgrid[0:9,0:6].T.reshape(-1,2)*.025
  rows=[]
  for i in range(25):
    rvec=np.array([.02*i-.24,.2*np.sin(i),.05*np.cos(i)])
    tvec=np.array([-.15+.012*i,-.1+.008*(i%10),.9+.02*(i%8)])
    wide=cv2.projectPoints(obj,rvec,tvec,cal.wide.k,cal.wide.distortion)[0]
    narrow=cv2.projectPoints(obj,rvec,tvec+cal.t[:,0],cal.narrow.k,cal.narrow.distortion)[0]
    rows.append((obj.copy(),wide,narrow))
  train=rows[:20];heldout=rows[20:]
  recovered=fit_camera([r[0] for r in train],[r[1] for r in train],(640,400),'radtan')
  np.testing.assert_allclose(recovered.k,cal.wide.k,atol=.01)
  assert board_errors(heldout,cal.wide,cal.narrow,cal.r,cal.t)<.001
  assert board_errors(heldout,cal.wide,cal.narrow,cal.r,cal.t*2)>5
