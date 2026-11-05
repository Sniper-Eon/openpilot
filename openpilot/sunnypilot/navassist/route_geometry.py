# Adapted from Sniper-Eon/xpilot-plugins 219ea9ef7c360f73797a91691afa34e41399e0f9.
# Only bounded route transport/cache is ported; no newer host APIs.
"""Bounded display-only route transfer. No control inputs or freshness updates."""
from dataclasses import dataclass, replace
import base64
import hashlib
import json
import math
import re
import threading

MAX_BYTES = 128 * 1024
MAX_CHUNKS = 64
CHUNK_BYTES = 2048
PENDING_NS = 15_000_000_000
MODES = {'route_planned', 'realtime', 'simulation'}
COMMON = {'messageType', 'schemaVersion', 'sessionId', 'routeRevision', 'routeId'}
BODY_KEYS = {'schemaVersion', 'coordinateSystem', 'pathId', 'sourcePointCount', 'sourcePointIndices',
             'totalDistanceMeters', 'toleranceMeters', 'points'}


def _int(value, lo, hi):
  if type(value) is not int or not lo <= value <= hi:
    raise ValueError('geometry_integer')
  return value


def _pairs(pairs):
  out = {}
  for k, v in pairs:
    if k in out:
      raise ValueError('geometry_duplicate_key')
    out[k] = v
  return out


def _constant(value):
  raise ValueError('geometry_nonfinite')


def _json(body):
  return json.loads(body.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)


def _forward(lat, lon):
  x, y = lon - 105., lat - 35.
  dlat = -100 + 2*x + 3*y + .2*y*y + .1*x*y + .2*math.sqrt(abs(x))
  dlon = 300 + x + 2*y + .1*x*x + .1*x*y + .1*math.sqrt(abs(x))
  shared = (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
  dlat += shared + (20*math.sin(y*math.pi) + 40*math.sin(y/3*math.pi))*2/3
  dlat += (160*math.sin(y/12*math.pi) + 320*math.sin(y*math.pi/30))*2/3
  dlon += shared + (20*math.sin(x*math.pi) + 40*math.sin(x/3*math.pi))*2/3
  dlon += (150*math.sin(x/12*math.pi) + 300*math.sin(x/30*math.pi))*2/3
  rad = math.radians(lat)
  magic = 1-.006693421622965943*math.sin(rad)**2
  dlat = dlat*180/((6378245*(1-.006693421622965943))/(magic*math.sqrt(magic))*math.pi)
  dlon = dlon*180/(6378245/math.sqrt(magic)*math.cos(rad)*math.pi)
  return lat+dlat, lon+dlon


def gcj02_to_wgs84(lat, lon):
  """Numerical approximation for map display, never lane/control evidence."""
  if not (72.004 <= lon <= 137.8347 and .8293 <= lat <= 55.8271):
    return lat, lon
  a, b = lat, lon
  for _ in range(8):
    forward_a, forward_b = _forward(a, b)
    da, db = forward_a-lat, forward_b-lon
    a, b = a-da, b-db
    if max(abs(da), abs(db)) < 1e-9:
      break
  return a, b


@dataclass(frozen=True)
class Geometry:
  session_id: str
  route_revision: int
  route_id: str
  coordinate_system: str
  points: tuple
  wgs84_points: tuple
  source_point_indices: tuple
  source_point_count: int
  tolerance_meters: float
  path_id: int


class RouteGeometryCache:
  def __init__(self):
    self.lock = threading.RLock()
    self.geometry = None
    self.pending = None
    self.converting = None
    self.worker = None

  def _clear(self):
    self.geometry = self.pending = self.converting = None

  def _context(self, current, now):
    if current is None or current.is_stale(now):
      return None
    s = current.snapshot
    if s.navigation_mode not in MODES:
      self._clear()
      return None
    key = (s.session_id, s.route_revision)
    if self.geometry is not None and self.geometry.coordinate_system != s.coordinate_system:
      self._clear()
    for route in (self.geometry, self.converting):
      if route is not None and (key != (route.session_id, route.route_revision) or route.coordinate_system != s.coordinate_system):
        self._clear()
    if self.pending is not None and key != self.pending['key']:
      self.pending = None
    return key

  def current(self, current, now_ns):
    # Conversion/reassembly runs on ingress. Never stall the 20 Hz navigation loop.
    if not self.lock.acquire(blocking=False):
      return None
    try:
      return self.geometry if self._context(current, now_ns) is not None else None
    finally:
      self.lock.release()

  def _parse(self, raw, key, route_id, source_coordinates):
    d = _json(raw)
    if not isinstance(d, dict) or set(d) != BODY_KEYS or type(d['schemaVersion']) is not int or d['schemaVersion'] != 1:
      raise ValueError('geometry_schema')
    if d['coordinateSystem'] not in ('gcj02', 'wgs84') or d['coordinateSystem'] != source_coordinates:
      raise ValueError('geometry_coordinates')
    path = _int(d['pathId'], 0, 2**63-1)
    count = _int(d['sourcePointCount'], 2, 50_000)
    _int(d['totalDistanceMeters'], 0, 30_000_000)
    tolerance = d['toleranceMeters']
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 0 <= tolerance <= 5:
      raise ValueError('geometry_precision')
    points, indices = d['points'], d['sourcePointIndices']
    if not isinstance(points, list) or not 2 <= len(points) <= 4096 or not isinstance(indices, list) or len(indices) != len(points):
      raise ValueError('geometry_points')
    for pair in points:
      if not isinstance(pair, list) or len(pair) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in pair):
        raise ValueError('geometry_point')
      if not (-90 <= pair[0] <= 90 and -180 <= pair[1] <= 180):
        raise ValueError('geometry_point_bounds')
    for i, value in enumerate(indices):
      _int(value, 0, count-1)
      if i and value <= indices[i-1]:
        raise ValueError('geometry_point_order')
    if indices[0] != 0 or indices[-1] != count-1:
      raise ValueError('geometry_endpoints')
    frozen = tuple(tuple(pair) for pair in points)
    # Conversion is deferred to one bounded worker, never the UDP snapshot receiver.
    wgs = () if d['coordinateSystem'] == 'gcj02' else frozen
    return Geometry(*key, route_id, d['coordinateSystem'], frozen, wgs, tuple(indices), count, float(tolerance), path)

  def _convert(self, route):
    try:
      converted = replace(route, wgs84_points=tuple(gcj02_to_wgs84(*pair) for pair in route.points))
      with self.lock:
        if self.converting is route:
          self.geometry, self.converting = converted, None
    except Exception:
      with self.lock:
        if self.converting is route:
          self.converting = None

  def accept(self, body, current, now_ns):
    if not body or len(body) > 4096:
      raise ValueError('geometry_packet_size')
    d = _json(body)
    if not isinstance(d, dict):
      raise ValueError('geometry_envelope')
    hello = d.get('messageType') == 'route_geometry_hello'
    expected = COMMON if hello else COMMON | {'chunkIndex', 'chunkCount', 'payload'}
    if set(d) != expected or d['messageType'] not in ('route_geometry_hello', 'route_geometry_chunk') or type(d['schemaVersion']) is not int or d['schemaVersion'] != 1:
      raise ValueError('geometry_envelope')
    if not isinstance(d['routeId'], str) or re.fullmatch('[0-9a-f]{64}', d['routeId']) is None:
      raise ValueError('geometry_id')
    revision = _int(d['routeRevision'], 0, 2**63-1)
    with self.lock:
      key = self._context(current, now_ns)
      if key is None or key != (d['sessionId'], revision):
        raise ValueError('geometry_context')
      complete = self.geometry is not None and self.geometry.route_id == d['routeId']
      index = -1 if hello else _int(d['chunkIndex'], 0, MAX_CHUNKS-1)
      ack = dict(messageType='route_geometry_ack', schemaVersion=1, sessionId=key[0], routeRevision=key[1],
                 routeId=d['routeId'], chunkIndex=index, accepted=True, complete=complete)
      if hello:
        return ack
      count = _int(d['chunkCount'], 1, MAX_CHUNKS)
      if index >= count or not isinstance(d['payload'], str) or len(d['payload']) > 2800:
        raise ValueError('geometry_chunk')
      chunk = base64.b64decode(d['payload'], validate=True)
      if not 1 <= len(chunk) <= CHUNK_BYTES:
        raise ValueError('geometry_chunk_size')
      if self.geometry is not None or self.converting is not None:
        if not complete and (self.converting is None or self.converting.route_id != d['routeId']):
          raise ValueError('geometry_revision_conflict')
        return ack
      p = self.pending
      if p is None or now_ns-p['started'] > PENDING_NS:
        p = self.pending = dict(key=key, route_id=d['routeId'], count=count, started=now_ns, chunks={})
      if (p['route_id'], p['count']) != (d['routeId'], count):
        raise ValueError('geometry_transfer_conflict')
      if index in p['chunks'] and p['chunks'][index] != chunk:
        raise ValueError('geometry_duplicate_conflict')
      p['chunks'][index] = chunk
      if sum(map(len, p['chunks'].values())) > MAX_BYTES:
        self.pending = None
        raise ValueError('geometry_total_size')
      if len(p['chunks']) == count:
        raw = b''.join(p['chunks'][i] for i in range(count))
        self.pending = None
        if hashlib.sha256(raw).hexdigest() != d['routeId']:
          raise ValueError('geometry_hash')
        route = self._parse(raw, key, d['routeId'], current.snapshot.coordinate_system)
        if route.wgs84_points:
          self.geometry = route
          ack['complete'] = True
        else:
          if self.worker is not None and self.worker.is_alive():
            raise ValueError('geometry_conversion_busy')
          self.converting = route
          self.worker = threading.Thread(target=self._convert, args=(route,), daemon=True, name='nav-route-convert')
          self.worker.start()
      return ack

