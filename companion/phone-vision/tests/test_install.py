from pathlib import Path
import importlib.util,json,stat
import pytest
spec=importlib.util.spec_from_file_location('installer',Path(__file__).resolve().parents[1]/'install.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
SOURCE=Path(__file__).resolve().parents[1]/'c3'
def test_clean_install_has_independent_code_and_preserves_existing_configuration(tmp_path):
 a,b=tmp_path/'a',tmp_path/'b';module.install(SOURCE,a);module.install(SOURCE,b)
 token=(a/'connection-code').read_text();assert len(token.strip())>=32;assert token!=(b/'connection-code').read_text();assert stat.S_IMODE((a/'connection-code').stat().st_mode)==0o600
 assert json.loads((a/'blindspot-assist.json').read_text())['mode']=='shadow'
 existing='{"version":1,"mode":"shadow","custom":true}\n';(a/'blindspot-assist.json').write_text(existing)
 module.install(SOURCE,a);assert (a/'connection-code').read_text()==token;assert (a/'blindspot-assist.json').read_text()==existing
 assert list((a/'backups').glob('*/manifest.json'));assert not (tmp_path/'continue.sh').exists()
def test_invalid_existing_code_is_not_silently_rotated(tmp_path):
 (tmp_path/'connection-code').write_text('bad');(tmp_path/'start_bridge.sh').write_text('preserve me')
 with pytest.raises(ValueError):module.install(SOURCE,tmp_path)
 assert (tmp_path/'connection-code').read_text()=='bad';assert (tmp_path/'start_bridge.sh').read_text()=='preserve me'
def test_existing_device_roi_is_used_instead_of_other_install_geometry(tmp_path):
 legacy=tmp_path/'device-roi.json';legacy.write_text('{"my_device":true}')
 target=tmp_path/'install';module.install(SOURCE,target,legacy)
 assert json.loads((target/'roi.json').read_text())=={'my_device':True}
