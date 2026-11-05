"""Official pinned tinygrad out-of-band artifact, resident Metal state."""
import numpy as np
from jetlink.spec import spec_from_onnx
from tools.nav_bigmodel.session import MODEL_SHA


class MetalEngine:
  def __init__(self, onnx_path, artifact_path):
    from tinygrad import Device, Tensor
    from examples.openpilot.helpers import allocate_inputs, load_pickle
    self.spec = spec_from_onnx(str(onnx_path))
    if self.spec.sha256 != MODEL_SHA:
      raise ValueError('ONNX does not match the tested official model')
    self.Tensor, self.Device = Tensor, Device
    self.artifact = load_pickle(artifact_path, out_of_band=True)
    self.inputs = allocate_inputs(self.artifact['input_specs'])
    self.outputs = allocate_inputs(self.artifact['output_specs'])
    if set(self.inputs) != set(self.spec.input_shapes):
      raise ValueError('Artifact input names differ from ONNX')
    for name, value in self.inputs.items():
      if tuple(value.shape) != tuple(self.spec.input_shapes[name]):
        raise ValueError('Artifact shape differs from ONNX: ' + name)
    self.states = self.spec.state_pairs
    if len(self.states) != 5 or any(v not in self.outputs for v in self.states.values()):
      raise ValueError('Incomplete recurrent state ABI')
    self.reset()

  def reset(self):
    for name in self.states:
      self.inputs[name].assign(0).realize()
    self.Device['METAL'].synchronize()

  def run(self, feeds):
    if set(feeds) != set(self.inputs) - set(self.states):
      raise ValueError('Missing or unexpected inference inputs')
    for name, value in feeds.items():
      shape, dtype, _ = self.artifact['input_specs'][name]
      if value.shape != tuple(shape) or value.dtype != np.dtype(dtype):
        raise ValueError('Input ABI mismatch: ' + name)
      self.inputs[name].assign(self.Tensor(value, device='METAL')).realize()
    self.artifact['run'](**self.inputs, output_buffers=self.outputs)
    self.Device['METAL'].synchronize()
    arrays = {k: v.numpy() for k, v in self.outputs.items()}
    if not all(np.isfinite(v).all() for v in arrays.values()):
      self.reset()
      raise ValueError('Nonfinite recurrent state/output')
    result = arrays['outputs'].copy()
    for name, next_name in self.states.items():
      self.inputs[name].assign(self.outputs[next_name]).realize()
    self.Device['METAL'].synchronize()
    return result
