package com.garan.tesnav.model

import java.util.Locale

/** C3 observations. The location bridge may adapt GPS; lane fields never grant control permission. */
data class OemNavigationTelemetry(
    val gpsStatus: String,
    val latitude: Double?, val longitude: Double?, val accuracyValue: Double?,
    val hdop: Double?, val headingDeg: Double?, val speedValue: Double?,
    val mapAvailable: Boolean?, val controllerHealth: Int?, val alcState: Int?,
    val forkState: Int?, val abortReason: Int?, val navAvailable: Boolean?,
    val navUsage: Int?, val autosteerHealth: Int?, val plannerState: Int?, val navDistanceM: Int?,
    val roadEstimator: Int? = null, val oemLaneChangeState: Int? = null,
    // Optional source diagnostics. Ages are measured at C3; not GNSS fix certification.
    val gpsTimeMs: Long? = null, val gpsTimeAgeMs: Long? = null,
    val gpsPositionAgeMs: Long? = null, val gpsMotionAgeMs: Long? = null,
    val gpsAccuracyRaw: String? = null, val gpsAccuracyAgeMs: Long? = null,
) {
    fun displayText(): String {
        val gps = when (gpsStatus) {
            "observed" -> "车载 GPS 已接入"
            "jump" -> "车载 GPS 位置跳变 · 暂不采用"
            "invalid" -> "车载 GPS 数据无效"
            "stale" -> "车载 GPS 数据已过期"
            else -> "车载 GPS 等待数据"
        }
        val accuracy = accuracyValue?.let { String.format(Locale.ROOT, "%.1f 米", it) } ?: "未知"
        return if (gpsStatus == "observed") "$gps · 精度 $accuracy" else gps
    }
}
