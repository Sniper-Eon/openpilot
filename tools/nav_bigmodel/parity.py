"""Real Jetlink v3 client over loopback -> Metal -> full output parity.

No vehicle connection. The fixture files and result belong outside Git.
"""
import argparse
import json
import threading
import time
from pathlib import Path

import numpy as np
from jetlink.client import JetlinkClient
from jetlink.transport.base import LinkError
from jetlink.transport.tcp import TcpTransport
from tools.nav_bigmodel.engine import MetalEngine
from tools.nav_bigmodel.serve import serve
from tools.nav_bigmodel.session import Context


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  for name in ('onnx', 'artifact', 'feeds', 'expected', 'report'):
    parser.add_argument('--' + name, required=True, type=Path)
  args = parser.parse_args()
  if args.report.exists():
    raise ValueError('Report exists')
  feeds = dict(np.load(args.feeds, allow_pickle=False))
  expected = np.load(args.expected, allow_pickle=False)['outputs']
  engine, context = MetalEngine(args.onnx, args.artifact), Context()
  listener = TcpTransport.listen('127.0.0.1', 0)
  failures = []

  def worker():
    try:
      transport, _ = TcpTransport.accept(listener)
      serve(transport, engine, context)
    except LinkError:
      pass  # normal client-close at the end
    except BaseException as error:
      failures.append(repr(error))

  thread = threading.Thread(target=worker, daemon=True)
  thread.start()
  client = JetlinkClient.open_tcp('127.0.0.1', listener.getsockname()[1], name='nav-parity', want_hidden=True)
  durations, differences = [], []
  try:
    client.hello()
    spec = client.ensure_engine(engine.spec.sha256, engine.spec.nbytes)
    for i in range(len(expected)):
      context.update(feeds['nav_map'][i], feeds['navigation'][i])
      packed = np.zeros(spec.packed_nelem, np.float32)
      for name, (at, shape) in spec.packed_layout.items():
        packed[at] = feeds[name][i].reshape(-1)
      start = time.perf_counter()
      output = client.infer(feeds['new_img'][i], packed, frame_id=i, reset=i == 0, want_state=True)
      durations.append(time.perf_counter() - start)
      differences.append(float(np.max(np.abs(output - expected[i].reshape(-1)))))
    assert client.last_state['backend'] == 'METAL'
  finally:
    client.close(); listener.close(); thread.join(timeout=5)
  report = dict(frames=len(differences), maxAbsDifference=max(differences),
                exactlyEqual=all(x == 0 for x in differences), failures=failures,
                medianRoundTripMs=float(np.median(durations) * 1000),
                p95RoundTripMs=float(np.percentile(durations, 95) * 1000),
                transport='Jetlink v3 loopback TCP', physicalUSBValidated=False, deviceActivated=False)
  args.report.parent.mkdir(parents=True, exist_ok=True)
  args.report.write_text(json.dumps(report, indent=2))
  print(json.dumps(report))
  if failures or not report['exactlyEqual']:
    raise SystemExit(1)


if __name__ == '__main__':
  main()
