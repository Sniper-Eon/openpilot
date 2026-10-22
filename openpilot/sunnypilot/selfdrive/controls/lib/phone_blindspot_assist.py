"""Experimental extra veto before lane-change initiation; never grants clearance.

Mode is fixed at process startup. Missing/invalid configuration remains shadow.
The phone's observation-only packet stays control_eligible=False: only this
explicitly enabled local policy may consume it as an additional veto.
"""
from dataclasses import dataclass
import json
import math
from pathlib import Path

CONFIG_PATH = "/data/phone-vision/blindspot-assist.json"
OBSERVATION_PATH = "/dev/shm/phone_side_vehicles.json"
MAX_AGE_NS = 800_000_000


def bounded_json(path):
  with Path(path).open() as f:
    raw = f.read(16385)
  if len(raw) > 16384:
    raise ValueError("oversized")
  data = json.loads(raw)
  if not isinstance(data, dict):
    raise ValueError("not_object")
  return data


def load_mode(path=CONFIG_PATH):
  try:
    data = bounded_json(path)
    return "assist" if type(data.get("version")) is int and data["version"] == 1 and data.get("mode") == "assist" else "shadow"
  except (OSError, ValueError, TypeError, RecursionError, OverflowError):
    return "shadow"


@dataclass(frozen=True)
class PhoneSide:
  available: bool = False
  blocked: bool = False
  reason: str = "unavailable"


class PhoneBlindspotAssist:
  def __init__(self, mode=None, path=OBSERVATION_PATH):
    self.mode = load_mode() if mode is None else mode
    self.path = path
    self.stream = None
    self.last_capture = -1
    self.empty = [0, 0]
    self.states = (PhoneSide(), PhoneSide())

  @property
  def enabled(self):
    return self.mode == "assist"

  def unknown(self, reason):
    self.empty = [0, 0]
    self.states = (PhoneSide(reason=reason), PhoneSide(reason=reason))
    return self.states

  def read(self, now_ns):
    try:
      data = bounded_json(self.path)
      stamp, stream = data.get("updated_mono_ns"), data.get("stream_id")
      if (type(data.get("version")) is not int or data["version"] != 1 or
          data.get("source") != "tesnav-phone" or data.get("valid") is not True or
          data.get("control_eligible") is not False or
          not isinstance(stream, str) or not 8 <= len(stream) <= 128 or
          type(stamp) is not int or not 0 <= now_ns - stamp <= MAX_AGE_NS):
        return self.unknown("invalid_or_stale")
      if stream != self.stream:
        # Stream switches must not reuse counters or an old capture epoch.
        if stamp <= self.last_capture:
          return self.unknown("old_stream")
        self.stream = stream
        self.empty = [0, 0]
        self.states = (PhoneSide(), PhoneSide())
      if stamp < self.last_capture:
        return self.unknown("out_of_order")
      if stamp == self.last_capture:
        return self.states  # Re-reading the file cannot count as a new frame.
      if self.last_capture >= 0 and stamp - self.last_capture > MAX_AGE_NS:
        self.empty = [0, 0]
        self.states = (PhoneSide(), PhoneSide())
      self.last_capture = stamp
      states = []
      for i, side in enumerate(("left", "right")):
        if side not in data:
          self.empty[i] = 0
          states.append(PhoneSide(reason="missing_side"))
          continue
        value = data[side]
        if value is None:
          self.empty[i] += 1
          # Three distinct, fresh packets withdraw a previous phone veto.
          # This is NO confirmation that the physical blind spot is clear.
          if self.empty[i] >= 3:
            states.append(PhoneSide(True, False, "no_confirmed_phone_target"))
          elif self.states[i].blocked:
            states.append(PhoneSide(True, True, "target_release_pending"))
          else:
            states.append(PhoneSide(reason="warming_up"))
          continue
        self.empty[i] = 0
        confidence = value.get("confidence") if isinstance(value, dict) else None
        hits = value.get("hits") if isinstance(value, dict) else None
        if (type(confidence) in (int, float) and math.isfinite(confidence) and
            .30 <= confidence <= 1 and type(hits) is int and 3 <= hits <= 100000):
          # No range/speed release gate: neither has independent calibration.
          states.append(PhoneSide(True, True, "confirmed_phone_target"))
        else:
          states.append(PhoneSide(reason="unconfirmed_or_malformed_target"))
      self.states = tuple(states)
      return self.states
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
      return self.unknown("missing_or_malformed")
