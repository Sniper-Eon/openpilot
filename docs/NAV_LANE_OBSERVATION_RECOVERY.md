# Bounded recovery after lane observation loss

A brief loss of absolute lane position could invalidate a prepared navigation plan and permanently block that maneuver event. The coordinator now classifies fresh navigation with an unusable lane observation separately, removes the request immediately, and can re-evaluate the same event after stable recovery.

Recovery requires the same session, route and maneuver; valid consistent geometry and target direction; a confirmed neighbor, crossable boundary and clear OEM blindspot; released lamps and no driver intervention. The candidate must remain stable for 3 seconds. The recovery window is 10 seconds with at most 2 recovery attempts per event. A fresh request must still pass the original alignment, physical lamp feedback, crossing and automatic lane-change timers. Old readiness is never restored.

Driver cancellation, conflicting/hazard lamps, direction changes, invalid navigation, timeouts and already-started lane changes do not receive this automatic recovery. Persistent uncertainty continues to block a maneuver. These parameters have not been road-tuned; unit tests cannot establish positioning accuracy or real-road behavior.

The position writer also preserves its estimator explanation as diagnostic metadata. The read-only recorder captures bounded absolute-position and anchor-file snapshots with their ages, so future failures can distinguish anchor loss, count conflicts and stale observations. Existing validity checks and the phone wire protocol are unchanged. No APK update or model retraining is required for this change.

Validation: 107 targeted tests, including existing navigation/control and shadow-mode parity, pass on the Mac test environment. The staged modules import on the C3 runtime and the native planner/coordinator smoke check passes. Actual road behavior remains unverified.

Deploy the four related Python sources together and restart services while offroad. Keep the previous files for rollback. Annotation drafts, private device data, runtime configuration and compiled artifacts are not part of this source update.
