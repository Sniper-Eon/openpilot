from http.server import ThreadingHTTPServer
import io
import json
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

from openpilot.selfdrive.debug import device_console
from openpilot.sunnypilot.navassist.diagnostics import NavigationLogWriter, log_status, select_logs


@pytest.fixture
def nav_console(tmp_path, monkeypatch):
  writer = NavigationLogWriter(tmp_path)
  writer.write({'kind': 'sample', 'signals': {'navAssistStateSP': {'sequence': 42}}}, wall_ms=1000)
  writer.close(wall_ms=2000)
  (tmp_path / 'qlog.zst').write_bytes(b'must not be downloaded here')
  monkeypatch.setattr(device_console, 'navigation_log_status', lambda: log_status(tmp_path))
  monkeypatch.setattr(device_console, 'select_navigation_logs', lambda a, b: select_logs(a, b, tmp_path))
  monkeypatch.setattr(device_console, 'flush_recording', lambda: True)
  monkeypatch.setattr(device_console, 'require_offroad', lambda: None)
  monkeypatch.setattr(device_console, 'console_status', lambda: {'onroad': False})
  server = ThreadingHTTPServer(('127.0.0.1', 0), device_console.DeviceConsoleHandler)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  try:
    yield f'http://127.0.0.1:{server.server_port}'
  finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_navigation_http_download_is_separate_from_general_logs(nav_console):
  with urllib.request.urlopen(nav_console + '/api/navigation/logs/status', timeout=3) as response:
    assert json.load(response)['file_count'] == 1
  with urllib.request.urlopen(nav_console + '/api/navigation/logs/preview?start_ms=1000&end_ms=3000', timeout=3) as response:
    assert json.load(response)['navigation_only']
  with urllib.request.urlopen(nav_console + '/api/navigation/logs/download?start_ms=1000&end_ms=3000', timeout=3) as response:
    assert 'navigation-logs-' in response.headers['Content-Disposition']
    with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
      assert len(archive.namelist()) == 2
      assert archive.namelist()[0] == 'manifest.json'
      assert archive.namelist()[1].startswith('navigation/navdiag-')


def test_navigation_flush_and_invalid_range(nav_console):
  request = urllib.request.Request(nav_console + '/api/navigation/logs/flush', method='POST')
  with urllib.request.urlopen(request, timeout=3) as response:
    assert json.load(response)['flushed']
  with pytest.raises(urllib.error.HTTPError) as error:
    urllib.request.urlopen(nav_console + '/api/navigation/logs/download?start_ms=3000&end_ms=1000', timeout=3)
  assert error.value.code == 400


def test_navigation_download_keeps_existing_offroad_policy(nav_console, monkeypatch):
  def blocked():
    raise PermissionError('onroad')
  monkeypatch.setattr(device_console, 'require_offroad', blocked)
  with pytest.raises(urllib.error.HTTPError) as error:
    urllib.request.urlopen(nav_console + '/api/navigation/logs/download?start_ms=1000&end_ms=3000', timeout=3)
  assert error.value.code == 403


def test_navigation_panel_has_independent_controls():
  page = device_console.render_page().decode()
  assert 'id="navlogs-tab"' in page
  assert 'id="navlogs-panel"' in page
  assert 'id="navlog-start"' in page
  assert '/api/navigation/logs/download' in page
  assert '/api/logs/download' in page
