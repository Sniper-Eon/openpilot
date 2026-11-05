"""Read-only SSH route stream for the Mac renderer; no install or settings writes.

Requires this test branch already installed on C3 by a separately authorized
deployment. The default-off trial exporter must have been explicitly enabled.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

MAX_BYTES = 1_000_000


def normalize(data, remote_now_ns, request_start_ns, response_ns):
  if data.get('version') != 1:
    raise ValueError('Unsupported observation')
  exported = data['exported_monotonic_ns']
  observed = data['observation_monotonic_ns']
  if any(type(n) is not int for n in (remote_now_ns, exported, observed, request_start_ns, response_ns)):
    raise ValueError('Invalid clock values')
  if not (0 <= remote_now_ns-observed < 500_000_000 and observed <= exported <= remote_now_ns
          and 0 <= response_ns-request_start_ns
          and remote_now_ns-observed+response_ns-request_start_ns < 500_000_000):
    raise ValueError('Expired observation or transport')
  packet = copy.deepcopy(data['packet'])
  # Preserve observation age, then charge the ENTIRE request round trip.
  # Never compare C3 monotonic timestamps directly with Mac timestamps.
  packet['captured_monotonic_ns'] = request_start_ns-(remote_now_ns-observed)
  # Express GPS age at that capture point; the renderer adds elapsed time once.
  packet['position']['age_ms'] -= (exported-observed)/1e6
  for key in ('session_id', 'sequence', 'route_revision', 'route_id'):
    packet[key] = data[key]
  return packet


def remote():
  path = Path('/dev/shm/jetlink_nav_context.json')
  print('{"ready":true}', flush=True)
  for request in sys.stdin:
    if request != 'read\n':
      break
    try:
      with path.open('rb') as source:
        raw = source.read(MAX_BYTES+1)
      if len(raw) > MAX_BYTES:
        raise ValueError('Oversize route')
      reply = dict(data=json.loads(raw), remote_now_ns=time.monotonic_ns())
    except Exception:
      reply = {}
    print(json.dumps(reply, allow_nan=False, separators=(',', ':')), flush=True)


def read_reply(stream, deadline_ns):
  response = bytearray()
  while not response.endswith(b'\n'):
    remaining = (deadline_ns-time.monotonic_ns())/1e9
    if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
      raise TimeoutError('Route transport timeout')
    chunk = os.read(stream.fileno(), 65536)
    if not chunk or len(response)+len(chunk) > MAX_BYTES:
      raise ValueError('Route transport closed or oversized')
    response.extend(chunk)
  return json.loads(response)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--remote', action='store_true', help=argparse.SUPPRESS)
  parser.add_argument('--host')
  parser.add_argument('--identity', type=Path)
  args = parser.parse_args()
  if args.remote:
    remote()
    return
  if not args.host or args.host.startswith('-') or any(c.isspace() for c in args.host):
    parser.error('A single SSH host is required')
  command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=2',
             '-o', 'ServerAliveCountMax=2']
  if args.identity:
    command += ['-i', str(args.identity)]
  command += [args.host, 'cd /data/openpilot && python3 -m tools.nav_bigmodel.pull_context --remote']
  # One persistent, authenticated SSH connection; any timeout ends the stream.
  # Renderer EOF clears context and the inference-side TTL independently expires.
  process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
  try:
    if read_reply(process.stdout, time.monotonic_ns()+10_000_000_000) != {'ready': True}:
      raise ValueError('Unexpected remote helper')
    while True:
      start = time.monotonic_ns()
      process.stdin.write(b'read\n')
      reply = read_reply(process.stdout, start+500_000_000)
      end = time.monotonic_ns()
      try:
        packet = normalize(reply['data'], reply['remote_now_ns'], start, end)
      except (KeyError, TypeError, ValueError):
        packet = {}  # Explicit invalidation, not replay of the last good route.
      print(json.dumps(packet, allow_nan=False, separators=(',', ':')), flush=True)
      time.sleep(max(0, .1-(time.monotonic_ns()-start)/1e9))
  finally:
    process.terminate()
    try:
      process.wait(timeout=2)
    except subprocess.TimeoutExpired:
      process.kill()
      process.wait()


if __name__ == '__main__': main()
