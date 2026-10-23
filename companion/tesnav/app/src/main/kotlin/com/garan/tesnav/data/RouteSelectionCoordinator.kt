package com.garan.tesnav.data

import com.garan.tesnav.model.RouteChoice

internal enum class RouteSelectionOutcome { ALREADY_SELECTED, SELECTED, REJECTED }

internal class RouteSelectionCoordinator(
    private val selectRouteId: (Int) -> Boolean,
) {
    fun select(routeId: Int, choices: List<RouteChoice>, selectedRouteId: Int?): RouteSelectionOutcome {
        if (choices.none { it.routeId == routeId }) return RouteSelectionOutcome.REJECTED
        if (selectedRouteId == routeId) return RouteSelectionOutcome.ALREADY_SELECTED
        return if (selectRouteId(routeId)) RouteSelectionOutcome.SELECTED else RouteSelectionOutcome.REJECTED
    }
}
