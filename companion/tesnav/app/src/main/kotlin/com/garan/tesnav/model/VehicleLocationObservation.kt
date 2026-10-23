package com.garan.tesnav.model

/** Pins one observation per advancing CAN clock; repeated ACKs never renew it. */
internal class VehicleLocationObservation {
    private var lastClock: Long? = null
    private var cached: NavigationLocationObservation? = null

    fun reset() { lastClock = null; cached = null }

    fun read(state: OemVehicleLaneState, elapsed: Long, wall: Long): NavigationLocationObservation? {
        fun held() = cached?.takeIf {
            elapsed >= it.receivedElapsedMs && elapsed-it.receivedElapsedMs+it.ageAtReceiptMs < MAX_AGE_MS &&
                wall >= it.measuredAtMs && wall-it.measuredAtMs < MAX_AGE_MS
        }
        fun invalid(): NavigationLocationObservation? { cached = null; return null }
        // A legacy/missing ACK is not a new invalid GPS measurement. Keep only the original deadline.
        val receipt = state.receivedAtElapsedMs ?: return held()
        val telemetry = state.navigationTelemetry ?: return held()
        if (elapsed < receipt) return invalid()
        if (elapsed - receipt >= MAX_AGE_MS) return held()
        if (telemetry.gpsStatus != "observed") return invalid()
        val clock = telemetry.gpsTimeMs ?: return invalid()
        val ages = listOf(telemetry.gpsTimeAgeMs, telemetry.gpsPositionAgeMs, telemetry.gpsMotionAgeMs)
        if (ages.any { it == null || it !in 0L until MAX_AGE_MS }) return invalid()
        val age = ages.filterNotNull().max() + elapsed - receipt
        if (age >= MAX_AGE_MS) return invalid()
        if (lastClock?.let { clock < it } == true) return invalid()
        if (clock == lastClock) return held()
        val lat = telemetry.latitude ?: return invalid()
        val lon = telemetry.longitude ?: return invalid()
        val accuracy = telemetry.accuracyValue ?: return invalid()
        val speed = telemetry.speedValue ?: return invalid()
        val heading = telemetry.headingDeg ?: return invalid()
        // Receipt minus the oldest contributing frame age: conservative observation timestamp.
        val observed = wall - age
        if (cached?.let { observed <= it.measuredAtMs } == true) return held()
        return NavigationLocationObservation("vehicle-can", observed, elapsed, age,
            lat, lon, accuracy, speed / 3.6, heading, NavigationCoordinateSystem.GCJ02,
            measurementTimeVerified = false, observationTimeOnly = true).also {
            cached = it; lastClock = clock
        }
    }

    private companion object {
        const val MAX_AGE_MS = 3_000L
    }
}
