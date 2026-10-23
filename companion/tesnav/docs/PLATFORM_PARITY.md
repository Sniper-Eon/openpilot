# Android / iOS navigation parity

Design update (2026-09-19): this is a product parity target, not a statement
that both implementations already match. Current differences and the proposed
source-health, session-ownership, ACK-size and recovery rules are recorded in
[`NAVASSIST_SHARED_CONTRACT.md`](NAVASSIST_SHARED_CONTRACT.md). This update
changes documentation only.

TesNav treats Android and iOS as two clients of one navigation contract. UI
layout may follow each platform, but the following user and NavAssist behavior
must remain equivalent:

- fuzzy destination search, current-address display, and selectable POI results;
- local recent search history (20 entries, newest first, deduplicated queries
  and selected places), repeat search/reselect, single deletion and clear-all;
- a missing-Key setup screen before AMap SDK objects are created, local Key
  persistence, a settings entry, and platform-specific official setup guidance;
- copyable iOS Bundle ID or Android package name and current signing SHA-1;
- up to three route alternatives with time, distance, toll, and traffic-light counts;
- real-time GPS navigation, simulation, stop, pause/resume simulation, internal
  voice guidance, and mute/resume voice;
- canonical v3 snapshot broadcast on unauthenticated UDP 4213, with a matching
  session/sequence acknowledgement before either App reports online;
- visible C3XL source address and connection status without a required token or
  pairing step;
- GCJ-02 route-relative location, route matching, route revisions, monotonic
  sequence numbers, stable maneuver event IDs, and the current 1200 ms default
  snapshot lifetime (transport TTL does not prove that SDK observations are fresh);
- the same maneuver vocabulary, including directional ramp, exit, merge, turn,
  U-turn, and roundabout events;
- navigation start forces both platforms to resume LAN broadcast immediately,
  so a changed C3XL address is learned from the next matching acknowledgement;
- the same lane-action vocabulary and the same invalid recommendation values
  (`15`, `22`, and `255`);
- GPS weakness is diagnostic and simulation is never control-active.

ACK compatibility must cover the complete UTF-8 datagram, including optional
vehicle feedback. The design target is a 2048-byte ACK limit on both platforms;
the current iOS 512-byte/four-field parser does not satisfy this target. Ordinary
reconnection must preserve navigation session/event identity, while runtime
restart must not automatically restore an active maneuver from cached state.
These are pending implementation and validation requirements.

Platform integrations outside navigation are intentionally not parity
requirements. Android's Home Assistant / Tesla reverse-sync and legacy
WebSocket debugging remain Android-only until separately specified.
