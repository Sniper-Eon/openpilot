package com.garan.tesnav.util

import com.garan.tesnav.model.CameraState
import com.garan.tesnav.model.CameraType
import com.garan.tesnav.model.WarningLevel

data class OverspeedResult(
    val speedLimitKph: Int?,
    val isOverspeed: Boolean,
    val hasSpeedCameraAhead: Boolean,
    val warningLevel: WarningLevel,
)

class OverspeedEvaluator(private val toleranceKph: Float = 3f) {
    fun evaluate(speedKph: Float, cameras: List<CameraState>, knownSpeedLimitKph: Int? = null): OverspeedResult {
        val speedCameras = cameras.filter { it.type in speedCameraTypes }
        val limit = speedCameras.mapNotNull { NavigationMappers.validSpeedLimit(it.limitSpeedKph) }.minOrNull()
            ?: NavigationMappers.validSpeedLimit(knownSpeedLimitKph)
        val overspeed = limit != null && speedKph > limit + toleranceKph
        return OverspeedResult(
            speedLimitKph = limit,
            isOverspeed = overspeed,
            hasSpeedCameraAhead = speedCameras.isNotEmpty(),
            warningLevel = when {
                overspeed && speedCameras.isNotEmpty() -> WarningLevel.CRITICAL
                overspeed -> WarningLevel.WARNING
                else -> WarningLevel.NONE
            },
        )
    }

    private companion object {
        val speedCameraTypes = setOf(
            CameraType.SPEED,
            CameraType.INTERVAL_START,
            CameraType.INTERVAL_END,
            CameraType.FLOW_SPEED,
        )
    }
}
