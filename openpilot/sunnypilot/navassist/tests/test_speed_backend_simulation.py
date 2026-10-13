"""Closed-loop, offline checks of the real planners and native solvers."""
from collections import deque
from pathlib import Path
import platform
import unittest

import numpy as np

from openpilot.cereal import custom, messaging
from openpilot.common.params import Params
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.sunnypilot.selfdrive.controls.lib.longitudinal_backends.factory import create_longitudinal_planner
from openpilot.sunnypilot.selfdrive.controls.lib.longitudinal_backends.registry import BackendId
from openpilot.tools.lib.logreader import LogReader


ROUTE_FIXTURE = Path(__file__).resolve().parents[2] / 'selfdrive/controls/tests/fixtures/tesla_legacy_planner_warm.rlog.zst'


def simulate(backend, *, navigation):
  source = list(LogReader(str(ROUTE_FIXTURE)))
  cp = next(m.carParams for m in source if m.which() == 'carParams')
  services = ['modelV2', 'carControl', 'carState', 'controlsState', 'vehicleParameters', 'radarState',
              'selfdriveState', 'carStateSP', 'navAssistStateSP', 'liveMapDataSP', 'selfdriveStateSP', 'gpsLocation', 'gpsLocationExternal']
  with OpenpilotPrefix():
    params = Params()
    for key, value in {
      'LongitudinalPlannerMode': int(backend), 'MpcTuningProfile': 0,
      'DynamicExperimentalControl': False, 'SmartCruiseControlVision': False,
      'SmartCruiseControlMap': False, 'SpeedLimitMode': 0, 'AccelPersonalityEnabled': True,
    }.items():
      params.put(key, value, block=True)
    planner = create_longitudinal_planner(cp, custom.CarParamsSP.new_message(), params=params)
    sm = messaging.SubMaster(services)
    messages = {s: messaging.new_message(s, valid=True) for s in services}
    for m in source:
      if m.which() in messages:
        messages[m.which()] = m.as_builder()
    cs = messages['carState'].carState
    cs.vCruise = cs.vCruiseCluster = 47.5
    cs.gasPressed = cs.brakePressed = False
    cs.steeringAngleDeg = 0.0
    cc = messages['carControl'].carControl
    cc.cruiseControl.override = False
    messages['selfdriveState'].selfdriveState.experimentalMode = False
    messages['controlsState'].controlsState.forceDecel = False
    messages['controlsState'].controlsState.curvature = 0.0
    radar = messages['radarState'].radarState
    radar.leadOne.present = radar.leadTwo.present = False
    radar.leadOne.modelProb = radar.leadTwo.modelProb = 0.0
    model = messages['modelV2'].modelV2
    model.action.desiredAcceleration = 0.0
    model.action.shouldStop = False
    nav = messages['navAssistStateSP'].navAssistStateSP
    nav.valid, nav.stale = navigation, not navigation
    nav.source, nav.mode = 'ios', 'realtime'
    nav.routeActive = nav.routeMatched = True
    nav.sessionId = 'offline-speed-test'
    nav.routeRevision = nav.maneuverEventId = 1
    nav.maneuver = 'turnRight'
    dt = 0.05
    delay = deque([0.0] * max(1, round(cp.longitudinalActuatorDelay / dt)))
    speed, accel, distance = 13.0, 0.0, 160.0
    rows = []
    for frame in range(400):
      enabled = frame >= 20
      cs.vEgo, cs.aEgo, cs.standstill = speed, accel, speed < 0.01
      cc.enabled = cc.longActive = cc.latActive = enabled
      messages['selfdriveState'].selfdriveState.enabled = enabled
      messages['controlsState'].controlsState.longControlState = 'pid' if enabled else 'off'
      nav.maneuverDistanceM = max(0.0, distance)
      now = 100.0 + frame * dt
      for m in messages.values():
        m.valid = True
        m.logMonoTime = int(now * 1e9)
      sm.update_msgs(now, list(messages.values()))
      planner.update(sm)
      output = float(planner.output_a_target)
      assert np.isfinite(output) and np.all(np.isfinite(planner.a_desired_trajectory))
      rows.append((distance, speed, output, planner.nav.is_active, float(planner.output_v_target)))
      delay.append(output if enabled else 0.0)
      accel = delay.popleft()
      speed = max(0.0, speed + accel * dt)
      distance -= speed * dt
    if backend == BackendId.TN_NO_DEC:
      assert planner.accel_controller.is_enabled
    return np.asarray(rows)


@unittest.skipUnless(platform.system() == 'Linux' and platform.machine().lower() == 'aarch64',
                     'Target-native closed-loop acceptance: Darwin acados artifacts give different trajectories')
class TestNavigationBackendSimulation(unittest.TestCase):
  def check_backend(self, backend):
    baseline = simulate(backend, navigation=False)
    navigation = simulate(backend, navigation=True)
    assert np.any(navigation[:, 3] == 1)
    assert np.any(navigation[:, 4] == 5.0)
    assert np.min(navigation[:, 2]) < -0.2
    assert navigation[-1, 1] < baseline[-1, 1] - 2.0
    assert navigation[-1, 1] < 8.5  # below the current 19 mph turn-desire threshold
    print(f'{backend.name}: baseline_final_kph={baseline[-1, 1] * 3.6:.2f},',
          f'nav_final_kph={navigation[-1, 1] * 3.6:.2f}, min_accel={np.min(navigation[:, 2]):.3f}')

  def test_official(self):
    self.check_backend(BackendId.OFFICIAL)

  def test_experimental(self):
    self.check_backend(BackendId.EXPERIMENTAL)

  def test_tn_no_dec(self):
    self.check_backend(BackendId.TN_NO_DEC)


if __name__ == '__main__':
  unittest.main()
