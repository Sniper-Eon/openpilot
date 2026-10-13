"""Read-only navigation recorder: no controller or publisher is created here."""
from __future__ import annotations

import time
import json

from openpilot.cereal import messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.sunnypilot.navassist.diagnostics import NavigationLogWriter, ingress_status_path, log_root, recording_metadata
from openpilot.sunnypilot.navassist.settings import SettingsCache, atomic_json


SERVICES = ('navAssistStateSP', 'navLaneIntentSP', 'laneTopologyStateSP', 'modelV2', 'modelDataV2SP',
            'carState', 'carStateSP', 'carControl', 'controlsState', 'longitudinalPlanSP', 'deviceState')


def collect_sample(sm, *, wall_ms: int, mono_ns: int) -> dict:
  signals = {}
  health = {}
  for name in SERVICES:
    health[name] = {
      'seen': sm.seen[name], 'alive': sm.alive[name], 'valid': sm.valid[name],
      'mono_ns': sm.logMonoTime[name],
      'age_ms': max(0, mono_ns - sm.logMonoTime[name]) / 1e6 if sm.seen[name] else None,
    }
    if not sm.seen[name]:
      continue
    value = sm[name]
    if name in ('navAssistStateSP', 'navLaneIntentSP', 'laneTopologyStateSP'):
      signals[name] = value.to_dict()
    elif name == 'carState':
      signals[name] = {key: getattr(value, key) for key in (
        'vEgo', 'aEgo', 'steeringAngleDeg', 'steeringTorque', 'steeringPressed', 'brakePressed', 'gasPressed',
        'leftBlinker', 'rightBlinker', 'leftBlindspot', 'rightBlindspot', 'vCruise',
      )}
    elif name == 'carStateSP':
      signals[name] = {'flags': value.flags}
    elif name == 'carControl':
      signals[name] = {'enabled': value.enabled, 'latActive': value.latActive, 'longActive': value.longActive,
                       'override': value.cruiseControl.override, 'actuators': value.actuators.to_dict()}
    elif name == 'controlsState':
      signals[name] = {'desiredCurvature': value.desiredCurvature, 'curvature': value.curvature,
                       'longControlState': str(value.longControlState), 'lateralControlState': value.lateralControlState.to_dict()}
    elif name == 'modelV2':
      signals[name] = {'frameId': value.frameId, 'laneChangeState': str(value.meta.laneChangeState),
                       'laneChangeDirection': str(value.meta.laneChangeDirection), 'desireState': list(value.meta.desireState)[:8],
                       'laneLineProbs': list(value.laneLineProbs)[:4], 'action': value.action.to_dict()}
    elif name == 'modelDataV2SP':
      signals[name] = {'laneTurnDirection': str(value.laneTurnDirection)}
    elif name == 'longitudinalPlanSP':
      signals[name] = {'source': str(value.longitudinalPlanSource), 'vTarget': value.vTarget, 'aTarget': value.aTarget,
                       'vision': value.smartCruiseControl.vision.to_dict(), 'accelController': value.accelController.to_dict()}
    elif name == 'deviceState':
      signals[name] = {'started': value.started}
  return {'kind': 'sample', 'wall_time_ms': wall_ms, 'mono_time_ns': mono_ns, 'health': health, 'signals': signals}


def main() -> None:
  cache = SettingsCache()
  params = Params()
  sm = messaging.SubMaster(list(SERVICES))
  writer = NavigationLogWriter()
  ratekeeper = Ratekeeper(20)
  previous_settings = None
  previous_started = False
  next_sample = next_status = 0.0
  next_ingress = 0.0
  ingress = {}
  last_sample_ms = None
  last_error = None
  root = log_root()
  try:
    while True:
      sm.update(0)
      now = time.monotonic()
      wall_ms = time.time_ns() // 1_000_000
      settings = cache.read()
      started = bool(sm.seen['deviceState'] and sm['deviceState'].started)
      if now >= next_ingress:
        next_ingress = now + 1.0
        try:
          path = ingress_status_path()
          ingress = json.loads(path.read_text()) if path.stat().st_size <= 4096 else {}
        except (OSError, ValueError):
          ingress = {}
      try:
        if settings != previous_settings or started != previous_started:
          writer.close()
          writer.metadata = recording_metadata(settings, params)
          previous_settings, previous_started = settings, started
        marker = root / 'flush.request'
        if marker.exists():
          writer.close()
          marker.unlink(missing_ok=True)
        if settings.logging_enabled and (started or now >= next_sample):
          sample = collect_sample(sm, wall_ms=wall_ms, mono_ns=time.monotonic_ns())
          sample['udp_ingress'] = ingress
          writer.write(sample, wall_ms=wall_ms)
          last_sample_ms = wall_ms
          next_sample = now + (0.05 if started else 1.0)
        last_error = cache.error
      except (OSError, ValueError) as error:
        last_error = str(error)
      if now >= next_status:
        next_status = now + 5.0
        try:
          atomic_json(root / 'status.json', {
            'updated_ms': wall_ms, 'last_sample_ms': last_sample_ms,
            'recording_enabled': settings.logging_enabled, 'error': last_error,
          })
        except OSError:
          pass
      ratekeeper.keep_time()
  finally:
    writer.close()


if __name__ == '__main__':
  main()
