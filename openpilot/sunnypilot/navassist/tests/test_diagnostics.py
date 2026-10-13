import gzip
import io
import json
import zipfile

import pytest

from openpilot.cereal import messaging
from openpilot.selfdrive.debug.local_diagnostics import LOCAL_DIAGNOSTIC_SERVICES
from openpilot.sunnypilot.navassist.diagnostics import NavigationLogWriter, NAVIGATION_ONLY_SERVICES, scan_logs, select_logs, stream_logs
from openpilot.sunnypilot.navassist.diagnosticsd import SERVICES, collect_sample


def test_navigation_is_excluded_from_generic_diagnostics():
  assert not NAVIGATION_ONLY_SERVICES.intersection(LOCAL_DIAGNOSTIC_SERVICES)
  assert 'trafficRadarState' in LOCAL_DIAGNOSTIC_SERVICES


def test_rotated_files_are_independent_parseable_and_bounded(tmp_path):
  writer = NavigationLogWriter(tmp_path, max_files=2, max_seconds=1)
  writer.metadata = {'kind': 'metadata', 'settings': {'enabled': True}}
  for index in range(3):
    writer.write({'kind': 'sample', 'sequence': index}, wall_ms=1000 + index * 1001)
  writer.close(wall_ms=5000)
  files = scan_logs(tmp_path)
  assert len(files) == 2
  assert not list(tmp_path.glob('*.partial'))
  records = [[json.loads(line) for line in gzip.decompress(item.path.read_bytes()).splitlines()] for item in files]
  assert [rows[0]['kind'] for rows in records] == ['metadata', 'metadata']
  assert [rows[1]['sequence'] for rows in records] == [1, 2]


def test_download_contains_only_navigation_and_manifest(tmp_path):
  writer = NavigationLogWriter(tmp_path)
  writer.write({'kind': 'sample', 'value': float('nan')}, wall_ms=1000)
  writer.close(wall_ms=2000)
  (tmp_path / 'qlog.zst').write_bytes(b'not navigation')
  (tmp_path / 'spdiag-private.zst').write_bytes(b'not navigation')
  real = scan_logs(tmp_path)[0].path
  (tmp_path / 'navdiag-0000000001000-0000000002000-12345678.jsonl.gz').symlink_to(real)
  files = select_logs(1000, 3000, tmp_path)
  assert len(files) == 1
  output = io.BytesIO()
  stream_logs(files, output, start_ms=1000, end_ms=3000)
  with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
    assert archive.namelist() == ['manifest.json', f'navigation/{real.name}']
    assert not json.loads(archive.read('manifest.json'))['contains_other_diagnostics']
    assert json.loads(gzip.decompress(archive.read(f'navigation/{real.name}')))['value'] is None


@pytest.mark.parametrize('start,end', [(2000, 1000), (-1, 2000), (0, 8 * 24 * 3600 * 1000)])
def test_invalid_download_ranges_fail(start, end, tmp_path):
  with pytest.raises(ValueError):
    select_logs(start, end, tmp_path)


def test_sample_records_required_context_without_full_model_payload():
  class SM(dict):
    pass
  sm = SM({name: getattr(messaging.new_message(name), name) for name in SERVICES})
  sm.seen = sm.alive = sm.valid = dict.fromkeys(SERVICES, True)
  sm.logMonoTime = dict.fromkeys(SERVICES, 1_000_000_000)
  sample = collect_sample(sm, wall_ms=2000, mono_ns=1_100_000_000)
  assert sample['health']['modelV2']['age_ms'] == 100
  assert 'desireState' in sample['signals']['modelV2']
  assert 'laneTurnDirection' in sample['signals']['modelDataV2SP']
  assert 'leftRawMarking' in sample['signals']['laneTopologyStateSP']
  assert 'leftBlinker' in sample['signals']['carState']
  assert 'position' not in sample['signals']['modelV2']
  assert 'can' not in sample['signals']
  json.dumps(sample, allow_nan=False)
