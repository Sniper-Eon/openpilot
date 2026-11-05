# Mac navigation-model / Jetlink test branch

This branch is based on `Sniper-Eon/openpilot:codex/egpu-jetlink-navassist`
at `bbf29f5fa937fbb2080dc27b51e2e9680fc41081`. It prepares a **shadow test**:
the existing small model supplies vehicle outputs; the Mac evaluates the
navigation model. It is not a validated autonomous-navigation release.

## Pinned components

- Official model source: commaai/openpilot `afbf2e547e9319e2eb9f515e1e4330af63705cec`.
- ONNX SHA256: `1d18c42ea4cd95c8bffab4635844b78b8e2d4e25b9de44a9c5ac2e0961371a2e`, 814591106 bytes.
- Official tinygrad compilation/runtime: `d3f09c9bbd542fbfbe68c8569a1173550c408969`, `DEV=METAL JIT=2`, out-of-band compiled artifact.
- Jetlink submodule: `913734280c33a40061874ebd01cd005210f43024`, API 1, protocol 3. No submodule modifications.
- AGNOS target: **19.9**. C3XL must have the explicit `c3xl` hardware profile.
  Generic `comma tici` is not sufficient to identify C3XL. Dedicated C3/C3XL
  boot images and hash allowlists are retained. An existing 19.9 installation
  skips flashing. The baseline cabin-camera policy is unchanged.

## What is implemented

1. `JetlinkNavTrialEnabled`, BOOL, default false, independently selects the
   pinned model without overwriting the saved model-manager choice.
2. The test branch never promotes an external model into the driving path.
   Its guard uses the pinned joiner's existing small-model/shadow path only.
   Turning the master off closes the link asynchronously and retains the
   small model. Reenable requires a new modeld session. Existing CAN, planner,
   safety and Jetlink timeout limits are unchanged.
3. Mac Metal engine with exact ABI checks, five recurrent states, resets on
   new session/leave/fault, finite-output checks and strict frame ordering.
4. Jetlink USB host transport and loopback TCP test transport. The model is
   preloaded on the Mac; arbitrary model upload and Mac power-off are refused.
5. A separate Mac navigation context interface. Missing or expired context
   clears BOTH map and instruction vector rather than retaining the old route.
   Navigation computation does not run on Android.

## Mac setup

Use Python 3.12 and the pinned tinygrad checkout. Install
`tools/nav_bigmodel/requirements-mac.txt` into a dedicated environment.
Initialize `jetlink_repo`. Add the repository root, `jetlink_repo` and the
pinned tinygrad checkout to `PYTHONPATH`; set `DEV=METAL JIT=2`.

Compile the verified ONNX with that tinygrad checkout's
`examples/openpilot/compile_onnx.py --out-of-band`. Keep its output and all
out-of-band buffer files together. Load only locally trusted compiled artifacts;
they are Python pickles. Weights and artifacts are intentionally not in Git.

Start the Mac service after a separate device test installation/configuration:

```sh
python -m tools.nav_bigmodel.serve --usb \
  --onnx /absolute/path/big_driving_supercombo.onnx \
  --artifact /absolute/path/big_driving_tinygrad.pkl \
  --nav-context /absolute/private/path/nav-context.npz
```

USB mode requires the existing Jetlink gadget to be enabled on C3. This command
does not install software, select a gadget, enable the trial, restart a process,
or flash a device. A missing USB device is an error. macOS/libusb claim and USB
throughput are still awaiting physical validation. `--listen PORT` is loopback
only and is intended for the parity test.

## Navigation producer interface

`render_context` consumes one JSON observation per stdin line and writes the
atomic NPZ read by `serve`. Use an explicitly selected HTTPS PMTiles archive;
the public archive used during experiments is not guaranteed identical to the
official hosted archive.

```sh
python -m tools.nav_bigmodel.render_context \
  --archive-url https://build.protomaps.com/20251201.pmtiles \
  --cache /absolute/private/path/map-cache \
  --output /absolute/private/path/nav-context.npz
```

Each observation has these fields:

| Field | Contract |
| --- | --- |
| `captured_monotonic_ns` | Observation capture timestamp in this Mac's monotonic clock; must be under 500 ms old. Do not refresh an old packet's timestamp. |
| `active` | Boolean true only for the currently accepted active route. |
| `coordinate_system` | Exactly `wgs84`; raw GCJ02 is rejected. |
| `route` | Current route as `[longitude, latitude]` pairs. Route and position must share datum and route revision. |
| `position` | `longitude`, `latitude`, `speed_mps`, `has_fix`, `age_ms`; qualified, source age under 2 seconds. |
| `guidance` | `valid`, `age_ms`, official Valhalla `command`, `distance_m`; under 2 seconds old. No command inferred merely from a lane recommendation. |

The renderer retains official route projection and speed extrapolation.
Commands use the official 47-vector representation: one maneuver slot plus
distance/100. The output NPZ contains float32 `nav_map (1,1,256,256)` in raw
grayscale 0..255, float32 `navigation (1,47)` and `captured_monotonic_ns`.
Map rendering exceeding the observation lifetime is rejected. EOF/error clears
the output; rereading a file never renews its lifetime.

**Live phone-to-producer integration is not completed.** This older branch
publishes `navAssistStateSP`, not the current xpilot `navassist/nav.state`, and
does not publish the complete route used by the newer xpilot branch. The JSON
contract must be fed from a verified route/position source before claiming live
navigation. Without it the model receives zero navigation inputs. Do not reuse
the newer branch's telemetry adapter blindly or label that zero-map run as a
navigation success. Clock synchronization, source freshness, route identity and
camera/context alignment need a real-device check.

## Checks and deployment status

```sh
python -m unittest discover -s tools/nav_bigmodel -p 'test_*.py'
python tools/sp_tesla_e2e/agnos_update_check.py
python -m tools.nav_bigmodel.parity --onnx ONNX --artifact PKL \
  --feeds RECORDED_FEEDS --expected DIRECT_OUTPUTS --report PRIVATE_REPORT
```

The parity runner uses the actual Jetlink client, loopback TCP and the real
Metal engine. It compares every output value and checks telemetry. It is not
a physical USB, C3 native build, activation or road test. See REPORT.md for
the measured results and the unresolved native-build checks.

Source preparation never changes the running device. Before installation:
complete the phone route producer, C3 native build including the new Params
key, physical USB/frame-age test and a parked shadow test. Current ~74 ms
loopback inference is slower than the 50 ms/20 Hz model budget. This branch
does not relax the budget or enable control to hide that limitation.
