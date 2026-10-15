import json
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.debug.lane_evidence import FrameWriter


def test_rotation_preserves_capture_identity_and_flushes_before_close(tmp_path):
  writer = FrameWriter(tmp_path, rotate_seconds=1, min_free_bytes=0)
  row = {'frame_id': 42, 'capture_mono_ns': 1234567, 'image': {'nv12_zlib': 'data'}}
  writer.write(row, now=0)
  assert json.loads(next(tmp_path.glob('*.partial')).read_text()) == row
  writer.write(row | {'frame_id': 43}, now=2)
  assert len(list(tmp_path.glob('*.jsonl'))) == 1
  writer.close()
  writer.close()
  assert sorted(json.loads(p.read_text())['frame_id'] for p in tmp_path.glob('*.jsonl')) == [42, 43]
  assert not list(tmp_path.glob('*.partial'))
  assert all(p.stat().st_mode & 0o777 == 0o600 for p in tmp_path.glob('*.jsonl'))


def test_byte_budget_prunes_old_segments_and_crash_partials(tmp_path):
  (tmp_path / 'wide-orphan.partial').write_bytes(b'old' * 50)
  writer = FrameWriter(tmp_path, max_bytes=200, rotate_seconds=1, min_free_bytes=0)
  for i in range(10):
    writer.write({'frame_id': i, 'image': 'a' * 100}, now=i * 2)
  writer.close()
  assert sum(p.stat().st_size for p in tmp_path.iterdir()) <= 200
  assert json.loads(next(tmp_path.glob('*.jsonl')).read_text())['frame_id'] == 9


def test_out_of_space_closes_frame_and_does_not_start_another(tmp_path, monkeypatch):
  writer = FrameWriter(tmp_path, min_free_bytes=0)
  writer.write({'frame_id': 1})
  writer.min_free_bytes = 2
  monkeypatch.setattr('openpilot.selfdrive.debug.lane_evidence.shutil.disk_usage',
                      lambda _: SimpleNamespace(free=1))
  with pytest.raises(OSError):
    writer.write({'frame_id': 2})
  assert not list(tmp_path.glob('*.partial'))
  assert json.loads(next(tmp_path.glob('*.jsonl')).read_text()) == {'frame_id': 1}


def test_oversized_record_cannot_exceed_recording_budget(tmp_path):
  writer = FrameWriter(tmp_path, max_bytes=20, min_free_bytes=0)
  with pytest.raises(OSError):
    writer.write({'data': 'a' * 30})
  assert not list(tmp_path.iterdir())
