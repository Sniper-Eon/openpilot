package com.garan.tesnav.data

internal fun routeObservationMatches(acceptedPathId: Long?, callbackPathId: Long, enginePathId: Long?): Boolean =
    acceptedPathId != null && acceptedPathId > 0 && callbackPathId == acceptedPathId && enginePathId == acceptedPathId

internal fun confirmedLanePath(acceptedPathId: Long?, guidancePathId: Long?, enginePathId: Long?,
                               routeRecalculating: Boolean): Long? =
    acceptedPathId?.takeIf { !routeRecalculating && it > 0 && guidancePathId == it && enginePathId == it }

internal fun com.garan.tesnav.model.NavigationState.acceptsUnkeyedRouteFacts(enginePathId: Long?): Boolean =
    routePlanned && unkeyedRouteFactsConfirmed &&
        confirmedLanePath(acceptedPathId, guidancePathId, enginePathId, routeRecalculating) != null

/** Associates a pending call with its captured listener token and diagnostic SDK request ID. */
internal class RouteRequestAssociation {
    private var generation = 0L
    private var pendingGeneration: Long? = null
    private var sdkRequestId: Int? = null
    private var runningGeneration: Long? = null
    var recoveryRequired: Boolean = false
        private set

    @Synchronized fun isPending(token: Long): Boolean = pendingGeneration == token

    // Cancelling an App request does not cancel the independent calculation in the SDK.
    @Synchronized fun startCall(token: Long): Boolean {
        if (pendingGeneration != token || runningGeneration != null) return false
        runningGeneration = token
        return true
    }

    @Synchronized fun completeCall(token: Long): Boolean {
        if (runningGeneration != token) return false
        runningGeneration = null
        recoveryRequired = false
        return true
    }

    @Synchronized fun timeout(token: Long): Boolean {
        if (!failInvocation(token)) return false
        recoveryRequired = runningGeneration != null
        return true
    }

    @Synchronized fun resetEngine(destroyed: Boolean): Boolean {
        if (!destroyed) return false
        invalidate()
        runningGeneration = null
        recoveryRequired = false
        return true
    }

    @Synchronized fun begin(): Long? {
        if (pendingGeneration != null || recoveryRequired) return null
        return (++generation).also { pendingGeneration = it; sdkRequestId = null }
    }

    @Synchronized fun bind(token: Long, requestId: Int) {
        if (pendingGeneration == token && requestId > 0) sdkRequestId = requestId
    }

    @Synchronized fun matches(requestId: Int?): Boolean =
        pendingGeneration != null && sdkRequestId != null && sdkRequestId == requestId

    /** Only for a listener created and passed to this specific independent SDK invocation. */
    @Synchronized fun finishCall(token: Long): Boolean {
        if (pendingGeneration != token) return false
        invalidate()
        return true
    }

    @Synchronized fun failInvocation(token: Long): Boolean {
        if (pendingGeneration != token) return false
        invalidate()
        return true
    }

    @Synchronized fun finish(requestId: Int?): Boolean {
        if (!matches(requestId)) return false
        invalidate()
        return true
    }

    @Synchronized fun invalidate() {
        generation += 1
        pendingGeneration = null
        sdkRequestId = null
    }
}

/** Destination coordinates are the SDK path endpoint, not raw search coordinates. */
internal fun recalculatedRouteMatches(
    previousPathId: Long?, callbackPathId: Long, enginePathId: Long?,
    expectedEnd: com.garan.tesnav.model.GeoPoint?, actualEnd: com.garan.tesnav.model.GeoPoint?,
): Boolean = previousPathId != null && previousPathId > 0 && callbackPathId > 0 &&
    callbackPathId != previousPathId && callbackPathId == enginePathId &&
    expectedEnd != null && actualEnd != null &&
    expectedEnd.latitude in -90.0..90.0 && expectedEnd.longitude in -180.0..180.0 &&
    actualEnd.latitude in -90.0..90.0 && actualEnd.longitude in -180.0..180.0 &&
    kotlin.math.abs(expectedEnd.latitude - actualEnd.latitude) <= 0.00001 &&
    kotlin.math.abs(expectedEnd.longitude - actualEnd.longitude) <= 0.00001
