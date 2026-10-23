import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("renew_signing", Path(__file__).with_name("renew-signing.py"))
renew = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renew)


class RenewalTests(unittest.TestCase):
    def test_expiration_uses_utc_and_checks_48_hour_boundary(self):
        now = datetime(2026, 9, 7, tzinfo=timezone.utc)
        for hours, expected in ((-1, True), (48, True), (49, False)):
            profile = {"ExpirationDate": (now + timedelta(hours=hours)).replace(tzinfo=None)}
            self.assertEqual(renew.due(profile, now), expected)

    def test_other_apps_teams_and_devices_are_not_profile_targets(self):
        profile = {"Entitlements": {"application-identifier": "TEAM.com.garan.tesnav.ios"}, "ProvisionedDevices": ["phone"]}
        self.assertTrue(renew.matching_profile(profile, "TEAM", "phone"))
        self.assertFalse(renew.matching_profile(profile, "OTHER", "phone"))
        self.assertFalse(renew.matching_profile(profile, "TEAM", "other-phone"))
        profile["Entitlements"]["application-identifier"] += ".tests"
        self.assertFalse(renew.matching_profile(profile, "TEAM", "phone"))

    def test_offline_device_does_not_build_install_or_move_profiles(self):
        with patch.object(renew, "status", return_value=(None, "missing")), \
             patch.object(renew, "device_json", return_value={"devices": []}), \
             patch.object(renew.subprocess, "run") as run, patch.object(renew.shutil, "move") as move:
            renew.renew("phone")
            run.assert_not_called()
            move.assert_not_called()

    def test_running_navigation_is_not_interrupted(self):
        device = {"identifier": "core", "hardwareProperties": {"udid": "phone"},
                  "deviceProperties": {"ddiServicesAvailable": True}}
        answers = [{"devices": [device]}, {"runningProcesses": [{"executable": "/app/TesNavIOS.app/TesNavIOS"}]}]
        with patch.object(renew, "status", return_value=(None, "missing")), \
             patch.object(renew, "device_json", side_effect=answers), \
             patch.object(renew.subprocess, "run") as run:
            renew.renew("phone")
            run.assert_not_called()

    def test_paired_device_with_cached_ddi_false_is_probed(self):
        device = {"identifier": "core", "hardwareProperties": {"udid": "phone"},
                  "connectionProperties": {"tunnelState": "disconnected"},
                  "deviceProperties": {"ddiServicesAvailable": False}}
        answers = [{"devices": [device]}, {"runningProcesses": [{"executable": "/app/TesNavIOS.app/TesNavIOS"}]}]
        with patch.object(renew, "status", return_value=(None, "missing")), \
             patch.object(renew, "device_json", side_effect=answers) as probe:
            renew.renew("phone")
            self.assertEqual(probe.call_count, 2)

    def test_fresh_successful_install_does_not_contact_device(self):
        with patch.object(renew, "status", return_value=(datetime.now(timezone.utc) + timedelta(days=5), "last_successful_install")), \
             patch.object(renew, "device_json") as device:
            renew.renew("phone")
            device.assert_not_called()

    def test_failed_build_restores_only_matching_cached_profile(self):
        device = {"identifier": "core", "hardwareProperties": {"udid": "phone"},
                  "deviceProperties": {"ddiServicesAvailable": True}}
        profile = {"Entitlements": {"application-identifier": "TEAM.com.garan.tesnav.ios",
                                    "com.apple.developer.team-identifier": "TEAM"},
                   "ProvisionedDevices": ["phone"], "ExpirationDate": datetime(2026, 1, 1)}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cached = root / "Library/Developer/Xcode/UserData/Provisioning Profiles"
            cached.mkdir(parents=True)
            own = cached / "own.mobileprovision"
            other = cached / "other.mobileprovision"
            own.write_bytes(b"own-original")
            other.write_bytes(b"unrelated-original")
            def read(path):
                return {} if Path(path).name == other.name else profile
            with patch.object(renew, "STATE", root / "state"), patch.object(renew.Path, "home", return_value=root), \
                 patch.object(renew, "status", return_value=(None, "missing")), \
                 patch.object(renew, "device_json", side_effect=[{"devices": [device]}, {"runningProcesses": []}]), \
                 patch.object(renew, "read_profile", side_effect=read), \
                 patch.object(renew.subprocess, "check_output", return_value=""), \
                 patch.object(renew.subprocess, "run", side_effect=RuntimeError("build failed")):
                with self.assertRaisesRegex(RuntimeError, "build failed"):
                    renew.renew("phone")
            self.assertEqual(own.read_bytes(), b"own-original")
            self.assertEqual(other.read_bytes(), b"unrelated-original")


if __name__ == "__main__":
    unittest.main()
