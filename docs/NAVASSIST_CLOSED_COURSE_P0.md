# NavAssist closed-course P0

## Scope

This branch accepts Android/iOS navigation observations over canonical v3 UDP
(or the compatible authenticated HTTP transport) and
exposes three closed-course behaviors: a bounded navigation speed ceiling
before a supported maneuver, a bounded physical pre-turn lamp, and an
experimental one-lane-at-a-time navigation target through SP's existing
DesireHelper and AutoLaneChangeController. On Tesla, both signal paths use the
bounded 0x3E9 turn-signal controller. The pre-turn lamp uses no lane-change
target; its physical feedback and cancellation tail are suppressed at the ALC
entrance while remaining available to SP's low-speed LaneTurnController.

The phone never supplies curvature, steering angle, acceleration, CarState, or
CAN. C3XL does not treat AMap's complete-road lane index as the same coordinate
as modelV2's local visible index. A fresh LaneInfo recommendation qualifies
active alignment only when it touches the maneuver-side road edge; unanchored
middle-lane recommendations remain display-only. When AMap has not yet
published LaneInfo, an ordinary/sharp/U-turn may select the visual extreme lane
in its direction inside 1 km; directional exit/ramp/merge maneuvers may do so
inside 2 km. C3XL requests one physical turn signal; SP requires current
ego-side dashed evidence, a clear blind spot and its configured
AutoLaneChangeController policy before starting. Relative edge alignment counts
one completed SP lane-change cycle, then observes again before another request.
The CP-inspired consistency filter requires a neighbor to remain stable for
0.5 seconds, pauses evidence while changing or while the driver steers, waits
2 seconds between completed changes, limits one maneuver event to five changes,
confirms an apparent road edge for 5 seconds, and requires a newly appearing
lane beyond that edge to remain stable for 3 seconds.

An ordinary navigation lane request follows CP's unknown-is-open policy but
still blocks confirmed solid paint. For a fresh `exit`/`ramp`/`merge` inside 50
metres, `forkNow` may additionally skip neighbor stability and ignore a solid
paint boundary.
It still requires fresh non-ambiguous topology, SP lateral authority, physical
lamp feedback, no pedal override, a clear blind spot, and no road-edge veto from
the existing SP detector. Ordinary lane alignment never receives this bypass.
For a continuous route revision, a changed maneuver event does not cancel the
lamp until SP's model-derived turn geometry has remained clear for 0.5 seconds;
a reroute/session change and the 60-second hard timeout still cancel directly.

This is not the full requested navigation stack. Android does not infer a
directional ramp/exit maneuver from road text alone, phone/tici positions are
not yet cross-correlated, and no intersection-turn curvature path is accepted
from the phone. Lane positioning remains one visual lane at a time through
SP's existing lane-change state machine.
Lane positioning alone never creates a navigation speed target. If a supported
turn or directional exit enters its computed comfort-braking window while the
last lane change is still active, maneuver deceleration remains eligible. The
navigation ceiling is retained through AMap distance zero; once SCC-V confirms
the curve, navigation hands speed ownership to SP's existing vision controller.

## Preconditions

- Use `navassist-track-p0` based on `dev-sp-egpu-lane`.
- Test only on a physically closed course with a safety driver and observer.
- Configure a dedicated private phone/C3XL network.
- Install the v3 TesNav App and perform its first automatic C3XL pairing while
  the vehicle is offroad on a controlled private LAN. No shared token is
  configured. C3XL can pin up to four P-256 App identities, adding each new
  identity only while offroad; unknown onroad keys are ignored.
- Synchronize phone and C3XL system clocks to within one second before arming.
- Physically secure the configured phone in the tested vehicle; P0 validates
  both devices independently inside their own data gates but does not yet prove
  that the two reported positions, headings, and speeds agree.
- Confirm the target is a Tesla C3XL, the official longitudinal backend is
  selected, and SP has active longitudinal authority before active deceleration.

TesNav generates a non-exportable P-256 private key in Android Keystore. C3XL
generates its own persistent P-256 device key and stores only the bounded App
public-key set in `NavAssistPairedApp`. First-use trust-on-first-use cannot
distinguish the owner from another live App on that LAN before a new key is
pinned, so do not perform initial pairing on a shared network. Reinstalling an
App changes its identity and requires offroad pairing; reset clears the entire
set. A fresh active navigation session cannot be preempted by another paired
App until it expires.

Do not place real track coordinates or private keys in the repository. P-256
signatures protect authenticity and integrity after TOFU pinning, not
confidentiality; do not use P0 on a shared network.

There is no per-drive Track Mode, shared-token, or geofence step. A fresh
realtime TesNav route becomes eligible only while SP has the required control
authority and the authenticated realtime route/data gates pass.

## Mandatory stationary checks

1. With no realtime phone navigation, verify `navassistd` remains available for
   pairing and transport, but `navAssistStateSP.valid` is false and all existing
   longitudinal sources are unchanged. `lane_topologyd` remains onroad-only.
2. Start a realtime route with SP disengaged. The HUD must report navigation unavailable;
   no speed target may change.
3. Broadcast malformed, oversized, unknown-field, and wrong-signature discovery
   requests. C3XL must remain silent. A valid request must receive a
   matching UDP 4213 acknowledgement for the sent session/sequence. Signed
   discovery on 7765 plus HTTP 7766 remains an explicit compatibility path.
4. Send missing-signature, wrong-signature, duplicate-sequence, decreasing
   route-revision, expired source-wall timestamp, contradictory inactive mode,
   malformed, non-finite, and oversized requests. Every request must be rejected
   or remain control-invalid and must not make `navAssistStateSP.valid` true.
5. Invalidate local localization. The state must report `localLocalization`
   while fresh matched phone guidance remains control-valid. Repeat with weak
   phone GPS and confirm the diagnostic remains visible without disabling the
   admitted route event.
6. Stop phone updates for more than 500 ms. The state must become stale and the
   speed ceiling must release upward at its bounded release rate, never jump to
   zero or command braking directly.
7. Restart the manager. The already-paired App must automatically rediscover the
   receiver, while old snapshots remain unable to affect planning until fresh
   realtime navigation and SP authority return.
8. Restart only `navassistd`, replay the last accepted signed request, and verify
   the persisted receive high-water mark rejects it.

## Active longitudinal progression

Use a straight, empty lane. A maneuver event must first be observed with enough
distance to meet the comfort admission calculation; a late event is rejected
for its entire lifetime.

Suggested progression, subject to the actual vehicle and track safety plan:

1. 10–20 km/h, supported left/right turn events.
2. 30 km/h, varied early and late instruction distances.
3. 40–50 km/h only for the same supported maneuver classes after lower-speed
   tests pass; do not test automatic exit/ramp handling in Android P0.
4. At most 60 km/h only after every lower-speed combination passes and a C3XL
   closed-loop replay confirms the navigation-only deceleration envelope.

For every combination exercise phone loss, route-revision change, gas, brake,
cancel, longitudinal disengagement, and a new maneuver event. Navigation must
never produce a speed ceiling lower than 2 m/s, request a stop, or make the plan
less conservative than lead/FCW/base-planner constraints.

P0 actively contributes a target only with the official longitudinal backend.
Verify that experimental and TN-NoDEC reject the current event. On the official
backend, attribute deceleration carefully: the navigation-only cruise component
is bounded at -1.2 m/s², while an existing lead/FCW/model source may legitimately
be more conservative and therefore produce stronger braking.

## Navigation-requested single-lane change checks

This path is experimental and must progress from stationary signal validation
to HIL/replay before any moving test. `TeslaTurnSignalValidation` must be
enabled offroad and the onroad cycle restarted so the matching Panda safety
capability is present. SP `AutoLaneChangeTimer` must also be set to an automatic
mode; `OFF` and `NUDGE` remain authoritative. Without confirmed physical lamp
feedback and current dashed evidence, SP must never begin lateral motion.

Use painted single dashed, single solid, and dashed-to-solid boundaries and
keep the target lane physically empty. Confirm the independent
`laneTopologyStateSP` message:

- becomes stale after model or image evidence ages out;
- clears `validForControl` on any raw `unknown` evidence even when the UI
  tracker remembers a previous marking;
- clears on ambiguous topology, calibration loss, or ego source-pair change;
- distinguishes relative visible lane index from total road lane count.
- preserves the left/right component order of mixed solid-dashed boundaries and
  allows crossing only when the ego-side component has current dashed evidence;
- never compares an unanchored AMap middle-lane index with a visual index;
  edge-qualified/fallback targets still require a real neighboring lane,
  physical one-sided lamp feedback, current dashed or unknown evidence, clear BSM, active
  SP lateral, and an automatic SP ALC mode;
- requires ordinary relative-edge observations to pass neighbor/edge stability,
  post-change cooldown, and the five-change event limit;
- keeps blocked lane alignment internal without lighting the physical signal;
  the lamp begins only when the crossing and BSM gates permit an immediate SP
  attempt, remains on through that attempt, and cannot trigger LaneTurnDesire;
- transfers a still-lit lamp from a completed lane change to a same-direction
  turn without masking the new model turn desire with the old lamp tail;
- stops new ordinary-turn edge alignment inside the existing turn approach
  window, while letting a started SP cycle finish before handing off;
- does not treat a change in the visible lane count as a route change or a
  temporary topology observation gap as real lateral-control loss;
- honors hold-until-cancel across SP's real starting-to-pre/off cycle; the
  coordinator performs stable completion confirmation and then cancels the
  physical lamp through the same controller used by the manual test action;
- exposes `forkNow`, `allowUnknownCrossing`, and `ignoreSolidBoundary` on the HUD
  whenever the final-fork exception is active; verify that stale/ambiguous
  geometry, road edge, BSM, pedals, and missing physical lamp still block it;
- tolerates at most one second of expected source-pair handoff while changing;
  a relative edge target completes one step from the SP lane-change cycle,
  while any future absolute target must prove a stable anchored index change;
- cancels on route/session change, pedals, physical-signal loss, stale input,
  direction conflict, or bounded timeout.

Never begin moving tests solely because unit tests pass. Capture a real model /
lane-topology replay and verify outer-line visibility cannot imitate a completed
lane change before authorizing closed-course motion.

## Immediate stop criteria

Stop the active test and return to HIL/root-cause analysis after any:

- unintended lateral actuation;
- failure of brake/cancel/driver override;
- accepted unauthenticated, replayed, or stale input;
- speed target below the configured non-stop floor;
- harsh braking caused by a late navigation event;
- route revision causing an old maneuver to reactivate;
- any behavior difference while navigation is invalid or SP is disengaged;
- model, camera, calibration, Panda, EPS, or longitudinal ownership fault.

Missing an instruction is the ordinary fallback. The vehicle must never use
hard braking or a reported road-edge/gore crossing to recover a missed turn or
exit. A solid-line crossing is permitted only in the explicit, HUD-visible
50-metre `forkNow` exception requested for this branch.
