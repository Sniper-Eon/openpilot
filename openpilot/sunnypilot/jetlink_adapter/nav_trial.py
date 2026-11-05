"""Explicit, default-off navigation model selection for this test branch.

The trial remains shadow-only: the existing Jetlink joiner warms the external
model while the small model supplies the driving output. No saved pick is
overwritten. This file stays stdlib-only for the resident gadget owner.
"""
PARAM = 'JetlinkNavTrialEnabled'
MODEL_REF = 'afbf2e547e9319e2eb9f515e1e4330af63705cec'
MODEL_SHA = '1d18c42ea4cd95c8bffab4635844b78b8e2d4e25b9de44a9c5ac2e0961371a2e'
MODEL_BYTES = 814591106


def shadow_only(enabled):
  try:
    return enabled() is True
  except Exception:
    return False


def override(key, enabled):
  if not shadow_only(enabled):
    return None
  if key == 'ModelManager_ActiveBundleChestnut':
    return {'ref': MODEL_REF, 'displayName': 'Official navigation model (Mac shadow trial)'}
  if key == 'JetlinkModelPointers':
    return {MODEL_REF: {'oid': MODEL_SHA, 'size': MODEL_BYTES}}
  return None


class ShadowGuard:
  """Pinned Jetlink 9137342 joiner guard: trial outputs never reach modeld.

Both adopting and sending use its existing small-model path; the promotion
path is never called for the trial. Disable closes the link and requires a
new modeld session before reenabling. No blocking inference is added.
  """
  def __init__(self, joined, small, enabled):
    self.__dict__.update(_joined_model=joined, _small_model=small, _enabled=enabled, _closed=False)

  def __getattr__(self, name):
    return getattr(self._small_model if self._closed else self._joined_model, name)

  def __setattr__(self, name, value):
    if name.startswith('_'):
      self.__dict__[name] = value
    else:
      setattr(self._small_model if self._closed else self._joined_model, name, value)

  def close(self):
    if not self._closed:
      self._closed = True
      # Native link shutdown may wait for IO; it must not stall modeld on disable.
      import threading
      self._closer = threading.Thread(target=self._joined_model.close, daemon=True)
      self._closer.start()

  def run(self, bufs, transforms, inputs, after_enqueue=None):
    if self._closed:
      return self._small_model.run(bufs, transforms, inputs, after_enqueue)
    joined = self._joined_model
    if not shadow_only(self._enabled):
      self.close()
      return self._small_model.run(bufs, transforms, inputs, after_enqueue)
    joined._adopt()
    joined._small_frames += 1
    return joined._run_small(bufs, transforms, inputs, after_enqueue)
