package com.garan.tesnav.data

import com.garan.tesnav.model.RouteChoice
import org.junit.Assert.assertEquals
import org.junit.Test

class RouteSelectionCoordinatorTest {
    @Test
    fun `selection uses route id rather than path id`() {
        val selectedIds = mutableListOf<Int>()
        val coordinator = RouteSelectionCoordinator { selectedIds += it; true }
        val choice = choice(routeId = 12, pathId = 9_000_000_001L)

        assertEquals(RouteSelectionOutcome.SELECTED, coordinator.select(12, listOf(choice), null))
        assertEquals(listOf(12), selectedIds)
    }

    @Test
    fun `unknown failed and already selected routes do not call SDK`() {
        val selectedIds = mutableListOf<Int>()
        val coordinator = RouteSelectionCoordinator { selectedIds += it; false }
        val choice = choice(routeId = 12, pathId = 900L)

        assertEquals(RouteSelectionOutcome.REJECTED, coordinator.select(99, listOf(choice), 12))
        assertEquals(RouteSelectionOutcome.ALREADY_SELECTED, coordinator.select(12, listOf(choice), 12))
        assertEquals(RouteSelectionOutcome.REJECTED, coordinator.select(12, listOf(choice), null))
        assertEquals(listOf(12), selectedIds)
    }

    private fun choice(routeId: Int, pathId: Long) = RouteChoice(
        routeId = routeId,
        pathId = pathId,
        label = "",
        distanceMeters = 1_000,
        durationSeconds = 120,
        tollYuan = 0,
        trafficLightCount = 1,
        selected = false,
    )
}
