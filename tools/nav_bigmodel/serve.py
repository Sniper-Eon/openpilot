"""Serve the pinned official Metal model to Jetlink, USB or loopback test TCP."""
import argparse
import os
import sys
import threading
import time
import zipfile
from pathlib import Path

import numpy as np
from jetlink import protocol as P
from jetlink.transport.base import LinkError, LinkTimeout
from jetlink.transport.tcp import TcpTransport
from tools.nav_bigmodel.session import Context, Session


def context_worker(path, context, stop):
  """Atomic NPZ interface on this Mac. Never refresh age merely by rereading."""
  while not stop.wait(0.05):
    try:
      if path.stat().st_size > 2_000_000:
        raise ValueError('Oversized navigation context')
      with np.load(path, allow_pickle=False) as data:
        stamp = int(data['captured_monotonic_ns']) / 1e9
        if not 0 <= time.monotonic() - stamp <= 0.5:
          raise ValueError('Navigation context expired')
        context.update(data['nav_map'], data['navigation'], now=stamp)
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile):
      context.clear()


def serve(transport, engine, context):
  session = Session(engine, context)
  try:
    while True:
      try:
        msg = transport.recv(timeout=2)
      except LinkTimeout:
        continue
      try:
        response = session.handle(msg.msg_type, bytes(msg.payload))
      except Exception as error:
        # Invalidate the session; an invalid output can never be reused.
        session.ready = False
        engine.reset()
        transport.send_json(P.Msg.ERROR, msg.seq, {'error': type(error).__name__, 'detail': str(error)}, timeout=2)
        continue
      if response is not None:
        kind, body = response
        transport.send(kind, msg.seq, (body,), timeout=2)
  finally:
    engine.reset()
    transport.close()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--onnx', required=True, type=Path)
  parser.add_argument('--artifact', required=True, type=Path)
  parser.add_argument('--nav-context', required=True, type=Path)
  mode = parser.add_mutually_exclusive_group(required=True)
  mode.add_argument('--usb', action='store_true')
  mode.add_argument('--listen', type=int, help='Loopback TCP port for bench tests only')
  args = parser.parse_args()
  os.environ['DEV'], os.environ['JIT'] = 'METAL', '2'
  from tools.nav_bigmodel.engine import MetalEngine
  engine = MetalEngine(args.onnx, args.artifact)
  context, stop = Context(), threading.Event()
  thread = threading.Thread(target=context_worker, args=(args.nav_context, context, stop), daemon=True)
  thread.start()
  try:
    while True:
      try:
        if args.usb:
          from tools.nav_bigmodel.usb_host import UsbHost
          transport = UsbHost()
        else:
          transport, _ = TcpTransport.listen_once('127.0.0.1', args.listen)
        serve(transport, engine, context)
      except (LinkError, OSError) as error:
        engine.reset()
        print(type(error).__name__ + ': link unavailable; retrying', file=sys.stderr)
        time.sleep(1)
  finally:
    stop.set()
    thread.join(timeout=1)


if __name__ == '__main__':
  main()
