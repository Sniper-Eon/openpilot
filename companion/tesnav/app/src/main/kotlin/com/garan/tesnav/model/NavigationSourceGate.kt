package com.garan.tesnav.model

internal fun isNewNavigationSample(sourceMs: Long?, previousMs: Long?, nowWallMs: Long): Boolean =
    sourceMs != null && sourceMs > 0 && sourceMs <= nowWallMs && (previousMs == null || sourceMs > previousMs)

/** Export-only guard; sender heartbeats never renew SDK observations. */
internal class NavigationSourceGate(
    private val sourceBudgetMs: Long,
    private val progressBudgetMs: Long,
) {
    private var armedAtMs: Long? = null
    private var wasHealthy = false
    private var recoveryRequired = false
    private var lastHealthyState: NavigationState? = null
    private var lostAtMs: Long? = null
    private var recoveryStartedMs: Long? = null
    private var recoveryLocationMs: Long? = null
    @Volatile var reason: String = "unconfirmed"
        private set

    @Synchronized
    fun arm(nowElapsedMs: Long) {
        armedAtMs = nowElapsedMs
        wasHealthy = false
        recoveryRequired = false
        lastHealthyState = null
        lostAtMs = null
        recoveryStartedMs = null
        recoveryLocationMs = null
    }

    @Synchronized
    fun disarm() {
        armedAtMs = null
        wasHealthy = false
        recoveryRequired = true
        lastHealthyState = null
        lostAtMs = null
        recoveryStartedMs = null
        recoveryLocationMs = null
    }

    @Synchronized
    fun prepare(state: NavigationState, nowElapsedMs: Long, nowWallMs: Long): NavigationState {
        fun age(stamp: Long?, budget: Long): Boolean =
            stamp != null && stamp >= 0 && stamp <= nowElapsedMs && nowElapsedMs - stamp <= budget
        val armed = armedAtMs
        // A changed progress observation is itself a callback. Unchanged matched
        // callbacks renew delivery evidence only, never the moving progress budget.
        val guidanceCallback = state.guidanceCallbackElapsedMs ?: state.guidanceReceivedElapsedMs
        // Bounded GPS near-zero noise tolerance, not proof of vehicle standstill
        // or execution permission. Both location and matching guidance must be fresh.
        val nearStationary = state.speedKph.isFinite() && state.speedKph in 0f..0.5f &&
            age(guidanceCallback, sourceBudgetMs)
        val candidate = state.navigationMode == NavigationMode.REALTIME && state.routePlanned && !state.routeRecalculating
        reason = when {
            !candidate -> "inactive"
            armed == null -> "requiresExplicitStart"
            sourceBudgetMs <= 0 || progressBudgetMs <= 0 -> "budgetsUnconfirmed"
            state.gpsSignalWeak -> "sourceInvalid"
            nowElapsedMs < 0 || nowWallMs < 0 -> "clockInvalid"
            state.acceptedPathId == null || state.acceptedPathId <= 0 || state.acceptedPathId != state.guidancePathId -> "routeUnconfirmed"
            state.routeMatched != true || state.currentStepIndex == null || state.currentStepIndex != state.guidanceStepIndex -> "guidanceUnconfirmed"
            state.locationReceivedElapsedMs == null || state.locationReceivedElapsedMs < armed -> "awaitingLocation"
            state.guidanceReceivedElapsedMs == null || state.guidanceReceivedElapsedMs < armed -> "awaitingGuidance"
            state.guidanceReceivedElapsedMs > nowElapsedMs -> "guidanceClockInvalid"
            guidanceCallback == null || guidanceCallback < armed || guidanceCallback > nowElapsedMs -> "guidanceClockInvalid"
            !age(state.locationReceivedElapsedMs, sourceBudgetMs) -> "sourceStalled"
            state.locationObservedAtMs == null || state.locationObservedAtMs < 0 || state.locationObservedAtMs > nowWallMs ||
                nowWallMs - state.locationObservedAtMs > sourceBudgetMs -> "sourceClockInvalid"
            state.guidanceObservedAtMs == null || state.guidanceObservedAtMs < 0 || state.guidanceObservedAtMs > nowWallMs -> "guidanceClockInvalid"
            !state.speedKph.isFinite() || state.speedKph < 0f -> "speedInvalid"
            !nearStationary && !age(state.guidanceReceivedElapsedMs, progressBudgetMs) -> "progressUnconfirmed"
            else -> "healthy"
        }
        if (reason == "healthy" && recoveryRequired) {
            val previous = lastHealthyState
            val lostAt = lostAtMs
            // Restore source delivery, not execution authority. Keep the existing event ID:
            // C3 owns admission, driver cancellation and already-interrupted actions.
            val advanced = previous != null && (state.routeRevision > previous.routeRevision ||
                (state.routeRevision == previous.routeRevision && state.acceptedPathId == previous.acceptedPathId &&
                    state.currentStepIndex!! > previous.currentStepIndex!!))
            val sameEvent = previous != null && state.routeRevision == previous.routeRevision &&
                state.acceptedPathId == previous.acceptedPathId && state.currentStepIndex == previous.currentStepIndex &&
                state.maneuver == previous.maneuver
            val fresh = lostAt != null && state.locationReceivedElapsedMs!! > lostAt &&
                guidanceCallback!! > lostAt
            if (fresh && sameEvent && recoveryStartedMs == null) {
                recoveryStartedMs = nowElapsedMs
                recoveryLocationMs = state.locationObservedAtMs
            }
            val stable = fresh && sameEvent && recoveryStartedMs != null &&
                nowElapsedMs - recoveryStartedMs!! >= 1_000L && state.locationObservedAtMs!! > recoveryLocationMs!!
            if (fresh && (advanced || stable)) {
                recoveryRequired = false
                lostAtMs = null
            } else {
                reason = "awaitingSourceRecovery"
                if (!fresh || !sameEvent) recoveryStartedMs = null
            }
        } else if (reason != "healthy") {
            recoveryStartedMs = null
            if (recoveryRequired) lostAtMs = nowElapsedMs
        }
        val healthy = reason == "healthy"
        if (wasHealthy && !healthy) {
            recoveryRequired = true
            lostAtMs = nowElapsedMs
            recoveryStartedMs = null
        }
        if (healthy) lastHealthyState = state
        wasHealthy = healthy
        return state.copy(navAssistControlAllowed = healthy)
    }
}
