from pathlib import Path
import stat

from openpilot.sunnypilot.navassist.identity import NavAssistDeviceIdentity, NavAssistPairingStore, verify_signature


class FakeParams:
  def __init__(self):
    self.values = {}

  def get(self, key):
    return self.values.get(key)

  def put(self, key, value, block=False):
    assert block
    self.values[key] = value

  def remove(self, key):
    self.values.pop(key, None)


def test_device_identity_persists_and_signs_with_a_p256_public_key(tmp_path):
  key_path = tmp_path / "device_key.pem"
  first = NavAssistDeviceIdentity.load_or_create(key_path)
  material = b"navassist identity test"

  assert len(first.device_id) == 32
  assert len(first.public_key) == 122
  assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
  assert verify_signature(first.public_key, material, first.sign(material))

  restarted = NavAssistDeviceIdentity.load_or_create(key_path)
  assert restarted.device_id == first.device_id
  assert restarted.public_key == first.public_key


def test_device_identity_can_be_generated_and_persisted_by_params():
  params = FakeParams()
  first = NavAssistDeviceIdentity.load_or_create(params=params)
  assert "NavAssistDevicePrivateKey" in params.values
  restarted = NavAssistDeviceIdentity.load_or_create(params=params)
  assert restarted.device_id == first.device_id
  assert restarted.public_key == first.public_key


def test_bounded_app_set_pairs_new_identities_only_offroad_and_preserves_existing_apps(tmp_path):
  params = FakeParams()
  pairing = NavAssistPairingStore(params)
  first = NavAssistDeviceIdentity.load_or_create(tmp_path / "first.pem")
  second = NavAssistDeviceIdentity.load_or_create(tmp_path / "second.pem")
  third = NavAssistDeviceIdentity.load_or_create(tmp_path / "third.pem")
  fourth = NavAssistDeviceIdentity.load_or_create(tmp_path / "fourth.pem")
  fifth = NavAssistDeviceIdentity.load_or_create(tmp_path / "fifth.pem")

  assert not pairing.authorize_or_pair(first.device_id, first.public_key, is_offroad=False)
  assert pairing.authorize_or_pair(first.device_id, first.public_key, is_offroad=True)
  assert not pairing.authorize_or_pair(second.device_id, second.public_key, is_offroad=False)
  assert pairing.authorize_or_pair(second.device_id, second.public_key, is_offroad=True)
  assert pairing.authorize_or_pair(third.device_id, third.public_key, is_offroad=True)
  assert pairing.authorize_or_pair(fourth.device_id, fourth.public_key, is_offroad=True)
  assert not pairing.authorize_or_pair(fifth.device_id, fifth.public_key, is_offroad=True)

  restarted = NavAssistPairingStore(params)
  assert restarted.authorize_or_pair(first.device_id, first.public_key, is_offroad=False)
  assert restarted.authorize_or_pair(second.device_id, second.public_key, is_offroad=False)
  restarted.reset()
  assert restarted.authorize_or_pair(fifth.device_id, fifth.public_key, is_offroad=True)


def test_legacy_single_app_record_migrates_when_a_second_phone_pairs_offroad(tmp_path):
  first = NavAssistDeviceIdentity.load_or_create(tmp_path / "first.pem")
  second = NavAssistDeviceIdentity.load_or_create(tmp_path / "second.pem")
  params = FakeParams()
  params.values["NavAssistPairedApp"] = {
    "version": 1, "keyId": first.device_id, "publicKey": first.public_key,
  }
  pairing = NavAssistPairingStore(params)
  assert pairing.authorize_or_pair(first.device_id, first.public_key, is_offroad=False)
  assert pairing.authorize_or_pair(second.device_id, second.public_key, is_offroad=True)
  record = params.values["NavAssistPairedApp"]
  assert record["version"] == 2
  assert [app["keyId"] for app in record["apps"]] == [first.device_id, second.device_id]


def test_paired_app_param_is_persistent_json_and_excluded_from_logs():
  params_keys = (Path(__file__).parents[3] / "common/params_keys.h").read_text()
  assert '{"NavAssistPairedApp", {PERSISTENT | DONT_LOG, JSON}}' in params_keys
  assert '{"NavAssistDevicePrivateKey", {PERSISTENT | DONT_LOG, STRING}}' in params_keys
  assert '{"NavAssistPairingReset", {CLEAR_ON_MANAGER_START, BOOL}}' in params_keys
