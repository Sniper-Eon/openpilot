package com.garan.tesnav.model

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.transformLatest

enum class OemLanePosition { UNKNOWN, LEFTMOST, MIDDLE, RIGHTMOST, SINGLE }

data class C3LaneDecision(val reason: String, val signalRequested: Boolean, val direction: String)

/** C3 vision lane number; null when the camera has no confirmed road-edge anchor. */
data class C3LanePosition(
    val valid: Boolean,
    val laneNumber: Int? = null,
    val laneCount: Int? = null,
    val reason: String? = null,
)

data class OemVehicleLaneState(
    val position: OemLanePosition = OemLanePosition.UNKNOWN,
    val positionValid: Boolean = false,
    val leftAllowed: Boolean = false,
    val rightAllowed: Boolean = false,
    val permissionValid: Boolean = false,
    val autoLaneChangeState: Int = 0,
    val blindspotValid: Boolean = false,
    val leftBlindspot: Boolean = false,
    val rightBlindspot: Boolean = false,
    val radarValid: Boolean = false,
    val leadPresent: Boolean = false,
    val leadDistanceM: Float? = null,
    val leadSpeedKph: Float? = null,
    val leadRelativeSpeedKph: Float? = null,
    val vehicleStateValid: Boolean = false,
    val egoSpeedKph: Float? = null,
    val lateralActive: Boolean = false,
    val brakePressed: Boolean = false,
    val gasPressed: Boolean = false,
    val laneChangeState: Int = 0,
    val laneChangeDirection: Int = 0,
    val receivedAtMs: Long = 0L,
    // Local receipt time only; never a CAN source timestamp or a wire field.
    val receivedAtElapsedMs: Long? = null,
    val navigationTelemetry: OemNavigationTelemetry? = null,
    val c3LaneDecision: C3LaneDecision? = null,
    val c3LanePosition: C3LanePosition? = null,
) {
    fun remainingDisplayMs(nowElapsedMs: Long, budgetMs: Long): Long {
        val received = receivedAtElapsedMs ?: return 0L
        if (received < 0L || nowElapsedMs < received || budgetMs <= 0L) return 0L
        val age = nowElapsedMs - received
        return if (age >= budgetMs) 0L else budgetMs - age
    }

    fun forDisplay(nowElapsedMs: Long, budgetMs: Long): OemVehicleLaneState =
        if (remainingDisplayMs(nowElapsedMs, budgetMs) > 0L) this else unavailableForDisplay()

    internal fun unavailableForDisplay() = OemVehicleLaneState(receivedAtMs = receivedAtMs)
}

/** A single cancellable deadline per observation; new feedback replaces the old deadline. */
@OptIn(ExperimentalCoroutinesApi::class)
internal fun Flow<OemVehicleLaneState>.withDisplayExpiry(
    budgetMs: Long,
    elapsedRealtimeMs: () -> Long,
): Flow<OemVehicleLaneState> = transformLatest { state ->
    var remainingMs = state.remainingDisplayMs(elapsedRealtimeMs(), budgetMs)
    emit(if (remainingMs > 0L) state else state.unavailableForDisplay())
    while (remainingMs > 0L) {
        delay(remainingMs)
        remainingMs = state.remainingDisplayMs(elapsedRealtimeMs(), budgetMs)
        if (remainingMs == 0L) emit(state.unavailableForDisplay())
    }
}
