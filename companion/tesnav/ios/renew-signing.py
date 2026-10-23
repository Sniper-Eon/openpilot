#!/usr/bin/env python3
"""Mac-side TesNav renewal. Read-only by default; --renew permits build/install.

Never launches or uninstalls the app. Only matching, near-expiry cached profiles
are moved to recoverable backups. Apple account authentication stays in Xcode.
"""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

IOS = Path(__file__).resolve().parent
BUNDLE = "com.garan.tesnav.ios"
APP = IOS / "DerivedData/Build/Products/Debug-iphoneos/TesNavIOS.app"
STATE = IOS / ".renewal"


def read_profile(path):
    result = subprocess.run(["security", "cms", "-D", "-i", str(path)], capture_output=True, check=True, timeout=15)
    return plistlib.loads(result.stdout)


def expiry(profile):
    return profile["ExpirationDate"].replace(tzinfo=timezone.utc)


def due(profile, now, hours=48):
    return expiry(profile) <= now + timedelta(hours=hours)


def matching_profile(profile, team, udid):
    return (profile.get("Entitlements", {}).get("application-identifier") == f"{team}.{BUNDLE}"
            and udid in profile.get("ProvisionedDevices", []))


def device_json(arguments):
    with tempfile.TemporaryDirectory(prefix="tesnav-device-") as directory:
        output = Path(directory) / "result.json"
        subprocess.run(["xcrun", "devicectl", *arguments, "--json-output", str(output)],
                       capture_output=True, check=True, timeout=30)
        return json.loads(output.read_text())["result"]


def status():
    receipt = STATE / "installed.json"
    if receipt.exists():
        record = json.loads(receipt.read_text())
        return datetime.fromisoformat(record["expires_at"]), "last_successful_install"
    profile = APP / "embedded.mobileprovision"
    return (expiry(read_profile(profile)), "local_build_only") if profile.exists() else (None, "missing")


def renew(device_id):
    now = datetime.now(timezone.utc)
    expires, source = status()
    if expires is not None and expires > now + timedelta(hours=48) and source == "last_successful_install":
        print(json.dumps({"status": "not_due", "expires_at": expires.isoformat()}))
        return
    devices = device_json(["list", "devices"])["devices"]
    device = next((d for d in devices if device_id in (d["identifier"], d["hardwareProperties"]["udid"])), None)
    # The list command caches DDI=false even for an available paired phone.
    # Process inspection below opens its tunnel and checks actual reachability.
    if device is None or device.get("connectionProperties", {}).get("tunnelState") == "unavailable":
        print('{"status":"waiting_for_device"}')
        return
    identifier, udid = device["identifier"], device["hardwareProperties"]["udid"]
    # Fail closed if process inspection is unavailable; never interrupt active navigation.
    processes = device_json(["device", "info", "processes", "--device", identifier])["runningProcesses"]
    if any("TesNavIOS.app/" in str(p.get("executable", "")) for p in processes):
        print('{"status":"waiting_for_app_to_close"}')
        return
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=IOS.parent, text=True)
    if dirty.strip():
        raise RuntimeError("Source has uncommitted changes; refusing unattended installation")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=IOS.parent, text=True).strip()
    original = read_profile(APP / "embedded.mobileprovision")
    team = original["Entitlements"]["com.apple.developer.team-identifier"]
    if not matching_profile(original, team, udid):
        raise RuntimeError("Requested iPhone is not covered by the existing TesNav profile")

    moved = []
    backup = STATE / "profile-backups" / now.strftime("%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True, mode=0o700)
    try:
        for folder in (Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
                       Path.home() / "Library/MobileDevice/Provisioning Profiles"):
            for path in folder.glob("*.mobileprovision"):
                if path.is_symlink():
                    continue
                try:
                    profile = read_profile(path)
                except (subprocess.SubprocessError, ValueError):
                    continue
                if matching_profile(profile, team, udid) and due(profile, now):
                    destination = backup / f"{len(moved)}-{path.name}"
                    shutil.move(str(path), destination)
                    moved.append((path, destination))
        with (STATE / "build.log").open("w") as log:
            commands = [
                ["xcodegen", "generate"], ["pod", "install", "--deployment"],
                ["xcodebuild", "-quiet", "-workspace", "TesNavIOS.xcworkspace", "-scheme", "TesNavIOS",
                 "-configuration", "Debug", "-destination", f"id={udid}", "-derivedDataPath", "DerivedData",
                 "-allowProvisioningUpdates", "build"],
            ]
            for command in commands:
                subprocess.run(command, cwd=IOS, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        updated = read_profile(APP / "embedded.mobileprovision")
        if not matching_profile(updated, team, udid) or due(updated, datetime.now(timezone.utc)):
            raise RuntimeError("Xcode did not produce a matching profile with more than 48 hours remaining")
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(APP)], check=True, timeout=30)
        # Recheck after building: the user may have started navigation meanwhile.
        processes = device_json(["device", "info", "processes", "--device", identifier])["runningProcesses"]
        if any("TesNavIOS.app/" in str(p.get("executable", "")) for p in processes):
            raise RuntimeError("App started during build; installation deferred")
        if (subprocess.check_output(["git", "status", "--porcelain"], cwd=IOS.parent, text=True).strip()
                or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=IOS.parent, text=True).strip() != revision):
            raise RuntimeError("Source changed during build; installation deferred")
        subprocess.run(["xcrun", "devicectl", "device", "install", "app", "--device", identifier, str(APP)],
                       check=True, timeout=180)
        record = {"status": "installed", "expires_at": expiry(updated).isoformat(),
                  "installed_at": datetime.now(timezone.utc).isoformat(), "revision": revision}
        temporary = STATE / "installed.json.tmp"
        temporary.write_text(json.dumps(record))
        os.replace(temporary, STATE / "installed.json")
        print(json.dumps(record))
    except Exception:
        for original_path, saved in moved:
            if not original_path.exists():
                shutil.move(str(saved), original_path)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renew", action="store_true")
    parser.add_argument("--device", default=os.environ.get("TESNAV_IOS_DEVICE_ID"))
    arguments = parser.parse_args()
    if not arguments.renew:
        expires, source = status()
        print(json.dumps({"expires_at": expires.isoformat() if expires else None, "source": source,
                          "renewal_due": expires is None or expires <= datetime.now(timezone.utc) + timedelta(hours=48)}))
        return
    if not arguments.device:
        parser.error("--renew requires --device or TESNAV_IOS_DEVICE_ID")
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        renew(arguments.device)


if __name__ == "__main__":
    main()
