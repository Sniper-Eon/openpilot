package com.garan.tesnav.model

internal enum class NavigationLocationSource { NONE, PHONE, VEHICLE }
internal enum class NavigationCoordinateSystem { UNKNOWN, WGS84, GCJ02 }

/** Independent source observation, not an SDK callback regenerated from an injected fix. */
internal data class NavigationLocationObservation(
    val sourceEpoch: String,
    val measuredAtMs: Long,
    val receivedElapsedMs: Long,
    val ageAtReceiptMs: Long,
    val latitude: Double,
    val longitude: Double,
    val accuracyM: Double?,
    val speedMps: Double?,
    val bearingDeg: Double?,
    val coordinateSystem: NavigationCoordinateSystem,
    val measurementTimeVerified: Boolean,
    // Explicit fallback policy: timestamp represents CAN observation, not a certified GNSS fix.
    val observationTimeOnly: Boolean = false,
)

internal data class NavigationLocationSelection(
    val source: NavigationLocationSource,
    val vehicleFixToInject: NavigationLocationObservation? = null,
    val reason: String,
)

/** A simulation can outlive stopNavi callbacks. Only the independent GPS stream
 * can supply a post-simulation origin; retain its existing 3 s observation lifetime.
 * SDK/display coordinates and heartbeat receipt times are never substitutes.
 */
internal fun independentPlanningOrigin(
    fix: NavigationLocationObservation?, nowElapsedMs: Long, nowWallMs: Long,
): GeoPoint? {
    if (fix == null || fix.sourceEpoch != "phone-gps" || !fix.measurementTimeVerified ||
        fix.coordinateSystem != NavigationCoordinateSystem.GCJ02 ||
        fix.measuredAtMs <= 0 || fix.measuredAtMs > nowWallMs || nowWallMs - fix.measuredAtMs >= 3000 ||
        fix.receivedElapsedMs < 0 || fix.receivedElapsedMs > nowElapsedMs || fix.ageAtReceiptMs !in 0L..2999L ||
        nowElapsedMs - fix.receivedElapsedMs >= 3000 - fix.ageAtReceiptMs ||
        !fix.latitude.isFinite() || fix.latitude !in -90.0..90.0 ||
        !fix.longitude.isFinite() || fix.longitude !in -180.0..180.0 ||
        fix.accuracyM?.let { it.isFinite() && it > 0 } != true) return null
    return GeoPoint(fix.latitude, fix.longitude)
}

/** Candidate selection only. Does not grant route, lamp or vehicle-control authority.
 * The caller must use independent phone observations to avoid an external-GPS feedback loop.
 * CAN fallback explicitly uses observation time; it does not claim a certified GNSS fix time.
 */
internal class NavigationLocationFallback {
    private var lastVehicleFix: Pair<String, Long>? = null
    private var lastElapsedMs: Long? = null

    fun reset() {
        lastVehicleFix = null
        lastElapsedMs = null
    }

    private fun usable(fix: NavigationLocationObservation?, elapsed: Long, wall: Long): Boolean {
        if (fix == null || (!fix.measurementTimeVerified && !fix.observationTimeOnly) || fix.sourceEpoch.isBlank() ||
            fix.coordinateSystem == NavigationCoordinateSystem.UNKNOWN ||
            fix.measuredAtMs <= 0 || fix.measuredAtMs > wall || wall - fix.measuredAtMs >= 3000 ||
            fix.receivedElapsedMs < 0 || fix.receivedElapsedMs > elapsed || fix.ageAtReceiptMs !in 0L..2999L ||
            elapsed - fix.receivedElapsedMs >= 3000 - fix.ageAtReceiptMs) return false
        return fix.latitude.isFinite() && fix.latitude in -90.0..90.0 &&
            fix.longitude.isFinite() && fix.longitude in -180.0..180.0 &&
            fix.accuracyM?.let { it.isFinite() && it > 0 && it <= 50 } == true &&
            fix.speedMps?.let { it.isFinite() && it in 0.0..83.333333 } == true &&
            fix.bearingDeg?.let { it.isFinite() && it >= 0 && it < 360 } == true
    }

    fun select(phone: NavigationLocationObservation?, vehicle: NavigationLocationObservation?,
               active: Boolean, nowElapsedMs: Long, nowWallMs: Long): NavigationLocationSelection {
        if (!active) {
            reset()
            return NavigationLocationSelection(NavigationLocationSource.NONE, reason = "inactive")
        }
        if (nowElapsedMs < 0 || nowWallMs < 0 || lastElapsedMs?.let { nowElapsedMs < it } == true) {
            reset()
            return NavigationLocationSelection(NavigationLocationSource.NONE, reason = "clockInvalid")
        }
        lastElapsedMs = nowElapsedMs
        if (usable(vehicle, nowElapsedMs, nowWallMs)) {
            val fix = vehicle!!
            val key = fix.sourceEpoch to fix.measuredAtMs
            val previous = lastVehicleFix
            if (previous?.first == key.first && key.second < previous.second) {
                return NavigationLocationSelection(NavigationLocationSource.NONE, reason = "vehicleTimeReversed")
            }
            val newFix = key != previous
            if (newFix) lastVehicleFix = key
            return NavigationLocationSelection(NavigationLocationSource.VEHICLE,
                if (newFix) fix else null, if (newFix) "vehiclePrimary" else "awaitingNewVehicleFix")
        }
        if (usable(phone, nowElapsedMs, nowWallMs)) {
            return NavigationLocationSelection(NavigationLocationSource.PHONE, reason = "phoneFallback")
        }
        return NavigationLocationSelection(NavigationLocationSource.NONE, reason = "noQualifiedLocation")
    }
}
