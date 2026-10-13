"""Small persistent navigation policy shared by the device UI and adapters."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
import time

from openpilot.common.hardware import PC
from openpilot.common.hardware.hw import Paths


@dataclass(frozen=True)
class NavAssistSettings:
  enabled: bool = True
  lane_change_enabled: bool = True
  turn_signal_enabled: bool = True
  turn_slowdown_enabled: bool = True
  turn_lane_lookahead_m: int = 1000
  exit_lane_lookahead_m: int = 2000
  signal_lead_time_s: int = 8
  turn_speed_kph: int = 18
  max_lane_changes: int = 5
  logging_enabled: bool = True


@dataclass(frozen=True)
class SettingSpec:
  title: str
  description: str
  minimum: int = 0
  maximum: int = 0
  step: int = 1
  unit: str = ''


SETTING_SPECS = {
  'enabled': SettingSpec('导航联动', '关闭后仍接收和显示手机导航，不发起导航变道、转弯灯或转弯减速。'),
  'lane_change_enabled': SettingSpec('导航自动靠边变道', '按导航目标请求 SP 原有变道功能；变道灯随此开关，仍执行现有标线、路缘和盲区判断。'),
  'turn_signal_enabled': SettingSpec('转弯提前打灯', '控制路口转弯的灯光请求；不影响自动变道需要的转向灯。'),
  'turn_slowdown_enabled': SettingSpec('导航转弯减速', '通过公共速度目标支持三套纵向；普通靠边变道本身不触发减速。'),
  'turn_lane_lookahead_m': SettingSpec('普通路口靠边提前距离', '进入此距离后才考虑为左转或右转靠边。', 100, 1500, 50, 'm'),
  'exit_lane_lookahead_m': SettingSpec('出口与匝道靠边提前距离', '进入此距离后才考虑为出口或匝道靠边。', 300, 3000, 100, 'm'),
  'signal_lead_time_s': SettingSpec('转弯打灯提前时间', '按当前车速换算距离，保留现有 40–250 米范围和距离余量。', 3, 12, 1, 's'),
  'turn_speed_kph': SettingSpec('普通转弯目标速度', '适用于普通左转/右转；急转、掉头与匝道保留各自目标。具体减速由所选纵向执行。', 10, 30, 1, 'km/h'),
  'max_lane_changes': SettingSpec('单路口连续变道次数', '同一导航事件最多请求的已完成变道次数。每次仍需重新确认车道条件。', 1, 5, 1, '次'),
  'logging_enabled': SettingSpec('独立导航日志', '单独记录导航、车道、灯光和控制上下文；网页独立下载，自动轮转且最多占用 128 MiB。'),
}


def settings_path() -> Path:
  root = Path(Paths.comma_home()) if PC else Path('/data')
  return root / 'navassist/settings.json'


def atomic_json(path: Path, value: dict) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
  try:
    with os.fdopen(fd, 'w') as output:
      json.dump(value, output, ensure_ascii=False, allow_nan=False)
      output.flush()
      os.fsync(output.fileno())
    os.replace(temporary, path)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def parse_settings(values: dict) -> NavAssistSettings:
  if not isinstance(values, dict) or set(values) - SETTING_SPECS.keys():
    raise ValueError('导航设置包含未知字段')
  defaults = asdict(NavAssistSettings())
  for key, value in values.items():
    spec = SETTING_SPECS[key]
    if isinstance(defaults[key], bool):
      if not isinstance(value, bool):
        raise ValueError(f'{spec.title}必须为开关值')
    elif (isinstance(value, bool) or not isinstance(value, int)
          or not spec.minimum <= value <= spec.maximum or (value - spec.minimum) % spec.step):
      raise ValueError(f'{spec.title}应为 {spec.minimum}–{spec.maximum}，步长 {spec.step}')
  return NavAssistSettings(**(defaults | values))


class SettingsStore:
  def __init__(self, path: Path | None = None):
    self.path = path if path is not None else settings_path()

  def read(self) -> NavAssistSettings:
    try:
      if self.path.stat().st_size > 8192:
        raise ValueError('导航设置文件过大')
      return parse_settings(json.loads(self.path.read_text()))
    except FileNotFoundError:
      return NavAssistSettings()

  def update(self, changes: dict) -> NavAssistSettings:
    settings = parse_settings(asdict(self.read()) | changes)
    atomic_json(self.path, asdict(settings))
    return settings


class SettingsCache:
  def __init__(self, store: SettingsStore | None = None):
    self.store = store if store is not None else SettingsStore()
    self.value = NavAssistSettings()
    self.next_read = 0.0
    self.error: str | None = None

  def read(self) -> NavAssistSettings:
    now = time.monotonic()
    if now >= self.next_read:
      self.next_read = now + 1.0
      try:
        self.value = self.store.read()
        self.error = None
      except (OSError, ValueError) as error:
        self.error = str(error)
    return self.value
