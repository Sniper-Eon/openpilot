package com.garan.tesnav.model

/** Map Android's physical GPS measurement clock to the local wall clock.
 * GNSS UTC can lead the system wall clock; freshness is measured by elapsed realtime.
 * Repeated delivery retains the measurement age instead of renewing it at receipt.
 */
internal fun phoneGpsLocalMeasurementTime(wallMs: Long, elapsedMs: Long, gpsElapsedMs: Long): Long? {
    if (wallMs <= 0 || elapsedMs < 0 || gpsElapsedMs < 0 || gpsElapsedMs > elapsedMs) return null
    val age = elapsedMs - gpsElapsedMs
    if (age >= 3000 || wallMs <= age) return null
    return wallMs - age
}
