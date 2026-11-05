# Validation — 2026-11-05

## Source provenance

- User-confirmed base: `Sniper-Eon/openpilot:codex/egpu-jetlink-navassist`,
  `bbf29f5fa937fbb2080dc27b51e2e9680fc41081`.
- New branch: `codex/nav-bigmodel-mac-jetlink`; independent worktree.
- Consulted upstream xpilot AGENTS/XPILOT and plugin/manifest definitions at
  `3f16c92d531bf6f4d9edf15d4696a89f72056523`. This legacy base does not have that
  plugin ABI; no xpilot-only hooks are assumed available.
- AGNOS source port: user xpilot checkout `a63a8c3e99b64a3cf43f8fa05c0071bbbb40e97f`.
  Scope: launcher selection, hardware identification, manifest hashes and
  boot-chain guards. No planner/CAN/panda changes.
- Official renderer files are pinned and attributed in `official_map/SOURCE.md`.
  Jetlink submodule remains `913734280c33a40061874ebd01cd005210f43024`.

## Failure-first checks

The 70-case AGNOS shell/OTA/partition-boundary check was copied and run before
the source port: exit 1, with old 19.7 selection and missing C3 guards exposed.
After the port it passes all 70 cases, exit 0. No partitions are accessed.

New interface/selection checks first failed on missing implementations. The
disable-path test also caught a synchronous one-second link close on modeld's
frame path; shutdown now runs separately and the small model returns immediately.

## Completed checks

| Check | Result | Scope |
| --- | --- | --- |
| `python tools/sp_tesla_e2e/agnos_update_check.py` | 70 cases, exit 0 | Actual launcher and extracted actual OTA function; simulated partition boundary |
| `python -m unittest discover -s tools/nav_bigmodel -p 'test_*.py'` | 9 tests, exit 0 | Context expiry/ABI, wrong model, malformed/nonfinite data, real Jetlink client reconnect, independent master, shadow/disable |
| Scoped pytest: hardware profile/manifests and Jetlink protocol/client/joiner, excluding the two native updater imports | 165 passed, 7 subtests passed; 2 deselected | CPU source checks; native exclusions below |
| Existing device `Parser.parse_outputs` on official outputs | 180 frames, finite arrays | Parser compatibility, not a complete modeld/native build |
| `tools.nav_bigmodel.parity` | 180 frames; maximum absolute difference **0.0** | Actual Jetlink v3 client, loopback TCP, real Metal engine versus direct inference |
| Loopback parity timing | Median **74.38 ms**, P95 **85.63 ms** | Serialized offline replay; not USB throughput or 20 Hz operation |
| `git diff --check` and changed Python compile checks | Exit 0 | Text/syntax only |
| Mac libusb backend discovery | Backend available; **0** Jetlink vendor gadgets visible | Read-only enumeration; no claim or physical transfer |

The parity fixture, full model outputs and driving data remain outside Git.
The navigation model was run with its five recurrent states preserved; handshake,
reset and disconnect paths clear state. The existing timeout/fallback budgets are
not loosened. The standalone Mac server does not select or enable a C3 setting.

## Native checks not completed

The initial broader test run exposed old 19.7 assertions, which were updated for
the explicitly requested 19.9 behavior. Two tests importing the complete native
updater cannot run in this Mac worktree: `openpilot/common/libparams_c.dylib` has
not been built. They are **not passed**. The 70-case AST/partition-boundary check
exercises the real OTA function separately without claiming native integration.
No C3 binary/firmware build or new Params-library build has been completed.

## Device and integration status

Read-only inspection found the running C3 already on AGNOS **19.9**, profile
`c3xl`, application commit `b9dfad2f8fcf66119a444be52efd4b869616c0d1`.
That is a different application from this branch. No install, settings changes,
restart, OS flashing or vehicle activation occurred.

The Mac receives images/scalars through Jetlink. Its separate map/context
producer has an explicit normalized JSON and atomic NPZ contract. The old base's
`navAssistStateSP` does not carry the complete route and is not the newer xpilot
plugin message ABI. The route intake/export and Mac SSH reader are now implemented in source, but
have not been exercised with the live phone/device. This branch must not be
described as end-to-end live navigation ready.
Missing context produces zero navigation inputs, visibly distinct in the test
contract from a navigation validation success.

Outstanding before device testing: live phone route adapter with datum, clock,
revision and freshness verification; C3 native build; physical USB and camera
warp/frame-age checks; parked shadow activation. Closed-loop route selection
and road validation remain unproven. External model control is deliberately
unavailable in this preparation branch; local small-model driving is retained.


## Route transport preparation, 2026-11-05 follow-up

- Ported only the bounded geometry cache from the user's xpilot-plugins commit
  `219ea9ef7c360f73797a91691afa34e41399e0f9`; no newer host hooks or message ABI.
  Upstream host specification revision remains
  `3f16c92d531bf6f4d9edf15d4696a89f72056523`.
- Added default-off route intake on the existing UDP endpoint, private atomic
  export on a separate worker and read-only Mac SSH context translation.
- Fixed renderer freshness to include transport/queue delay for GPS and commands.
  The new test failed on the old renderer; the new socket test failed on the old
  receiver constructor. Clock translation also has a regression rejecting combined
  remote age and round-trip delay exceeding 500 ms.
- Tests use synthetic phone packets and real localhost UDP sockets. No real phone,
  SSH device stream, USB model frames or driving outputs were used in this step.
- Command vector remains zero: only the complete route map supplies direction.
  Phone maneuver distance semantics remain unresolved. Conversion is approximate.
- No C3 installation, activation, firmware build or road validation performed.
- Final scoped checks: `unittest discover -s tools/nav_bigmodel -p 'test_*.py'`
  **15 passed**; `pytest` on `test_protocol.py` and `test_udp_receiver.py`
  **17 passed**; changed Python compile checks and `git diff --check` exit 0.
  Tests importing the existing UDP receiver require the project's cryptography
  dependency (installed only in the temporary Mac test environment).
