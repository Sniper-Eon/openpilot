package com.garan.tesnav.model

import org.junit.Assert.*
import org.junit.Test

class NavigationSourceGateTest {
    @Test fun `duplicate old missing and future SDK source times never renew observations`() {
        assertTrue(isNewNavigationSample(1_001, 1_000, 1_001))
        assertTrue(isNewNavigationSample(1_000, null, 1_001))
        for (stamp in listOf(null, -1L, 0L, 999L, 1_000L, 1_002L)) {
            assertFalse(isNewNavigationSample(stamp, 1_000, 1_001))
        }
        assertFalse(isNewNavigationSample(1_001, 1_000, 900))
    }

    private fun state() = NavigationState(
        navigationMode = NavigationMode.REALTIME, routePlanned = true, routeMatched = true,
        acceptedPathId = 7L, guidancePathId = 7L, currentStepIndex = 2, guidanceStepIndex = 2,
        locationObservedAtMs = 10_000L, guidanceObservedAtMs = 10_000L,
        locationReceivedElapsedMs = 100L, guidanceReceivedElapsedMs = 100L, speedKph = 30f,
        navAssistControlAllowed = true,
    )
    private fun gate() = NavigationSourceGate(1_000L, 2_000L).apply { arm(100L) }

    @Test fun `new runtime and uncalibrated budgets cannot restore cached active state`() {
        assertFalse(NavigationSourceGate(1_000, 2_000).prepare(state(), 100, 10_000).navAssistControlAllowed)
        for (budgets in listOf(0L to 2_000L, 1_000L to 0L)) {
            val gate = NavigationSourceGate(budgets.first, budgets.second).apply { arm(100) }
            assertFalse(gate.prepare(state(), 100, 10_000).navAssistControlAllowed)
            assertEquals("budgetsUnconfirmed", gate.reason)
        }
    }

    @Test fun `expiry sends inactive and fresh data alone cannot reactivate`() {
        val gate = gate()
        assertTrue(gate.prepare(state(), 1_100, 11_000).navAssistControlAllowed)
        assertFalse(gate.prepare(state(), 1_101, 11_001).navAssistControlAllowed)
        val fresh = state().copy(locationObservedAtMs = 12_000, guidanceObservedAtMs = 12_000,
            locationReceivedElapsedMs = 2_100, guidanceReceivedElapsedMs = 2_100)
        assertFalse(gate.prepare(fresh, 2_100, 12_000).navAssistControlAllowed)
        gate.arm(2_100)
        assertTrue(gate.prepare(fresh, 2_100, 12_000).navAssistControlAllowed)
    }

    @Test fun `inactive interlude does not clear required rearm`() {
        val gate = gate()
        assertTrue(gate.prepare(state(), 100, 10_000).navAssistControlAllowed)
        gate.prepare(state(), 1_101, 11_001)
        gate.prepare(state().copy(navigationMode = NavigationMode.IDLE), 1_102, 11_002)
        assertFalse(gate.prepare(state().copy(locationReceivedElapsedMs = 1_103,
            guidanceReceivedElapsedMs = 1_103, locationObservedAtMs = 11_003), 1_103, 11_003).navAssistControlAllowed)
    }

    @Test fun `stationary unchanged guidance is valid but moving stale guidance is not`() {
        val freshLocation = state().copy(speedKph = 0f, locationObservedAtMs = 20_000,
            locationReceivedElapsedMs = 10_100, guidanceCallbackElapsedMs = 10_100)
        assertTrue(gate().prepare(freshLocation, 10_100, 20_000).navAssistControlAllowed)
        assertFalse(gate().prepare(freshLocation.copy(speedKph = 1f), 10_100, 20_000).navAssistControlAllowed)
        assertFalse(gate().prepare(freshLocation.copy(currentStepIndex = 3), 10_100, 20_000).navAssistControlAllowed)
    }

    @Test fun `unknown old route and future clocks fail closed`() {
        for (input in listOf(
            state().copy(acceptedPathId = null), state().copy(guidancePathId = 8),
            state().copy(locationReceivedElapsedMs = 101), state().copy(locationObservedAtMs = 10_001),
            state().copy(guidanceObservedAtMs = 10_001), state().copy(routeMatched = null),
            state().copy(locationReceivedElapsedMs = 99),
        )) assertFalse(gate().prepare(input, 100, 10_000).navAssistControlAllowed)
    }

    @Test fun `simulation reroute and explicit stop cannot emit active`() {
        assertFalse(gate().prepare(state().copy(navigationMode = NavigationMode.SIMULATION), 100, 10_000).navAssistControlAllowed)
        assertFalse(gate().prepare(state().copy(routeRecalculating = true), 100, 10_000).navAssistControlAllowed)
        val gate = gate()
        gate.disarm()
        assertFalse(gate.prepare(state(), 100, 10_000).navAssistControlAllowed)
    }

    @Test fun `outage resumes only for a fresh later step or newer accepted route`() {
        for (next in listOf(
            state().copy(currentStepIndex = 3, guidanceStepIndex = 3),
            state().copy(routeRevision = 1, acceptedPathId = 8, guidancePathId = 8, currentStepIndex = 0, guidanceStepIndex = 0),
        )) {
            val gate = gate()
            assertTrue(gate.prepare(state(), 100, 10_000).navAssistControlAllowed)
            assertFalse(gate.prepare(state(), 1_101, 11_001).navAssistControlAllowed)
            val fresh = next.copy(locationObservedAtMs = 12_000, guidanceObservedAtMs = 12_000,
                locationReceivedElapsedMs = 2_100, guidanceReceivedElapsedMs = 2_100)
            assertFalse(gate.prepare(fresh.copy(guidanceReceivedElapsedMs = 100), 2_100, 12_000).navAssistControlAllowed)
            assertFalse(gate.prepare(fresh.copy(routeMatched = false), 2_100, 12_000).navAssistControlAllowed)
            assertTrue(gate.prepare(fresh.copy(locationObservedAtMs = 12_100, guidanceObservedAtMs = 12_100,
                locationReceivedElapsedMs = 2_200, guidanceReceivedElapsedMs = 2_200), 2_200, 12_100).navAssistControlAllowed)
            gate.disarm()
            assertFalse(gate.prepare(fresh.copy(routeRevision = 2), 2_100, 12_000).navAssistControlAllowed)
        }
    }

    @Test fun `inactive transition also cancels interrupted event`() {
        val gate = gate()
        assertTrue(gate.prepare(state(), 100, 10_000).navAssistControlAllowed)
        assertFalse(gate.prepare(state().copy(routeRecalculating = true), 101, 10_001).navAssistControlAllowed)
        assertFalse(gate.prepare(state(), 102, 10_002).navAssistControlAllowed)
        assertEquals("awaitingSourceRecovery", gate.reason)
    }

    @Test fun `backward step and different path without revision cannot resume cancelled event`() {
        val gate = gate()
        assertTrue(gate.prepare(state(), 100, 10_000).navAssistControlAllowed)
        assertFalse(gate.prepare(state(), 1_101, 11_001).navAssistControlAllowed)
        val fresh = state().copy(locationObservedAtMs = 12_000, guidanceObservedAtMs = 12_000,
            locationReceivedElapsedMs = 2_100, guidanceReceivedElapsedMs = 2_100)
        for (invalid in listOf(fresh.copy(currentStepIndex = 1, guidanceStepIndex = 1),
            fresh.copy(acceptedPathId = 8, guidancePathId = 8, currentStepIndex = 3, guidanceStepIndex = 3))) {
            assertFalse(gate.prepare(invalid, 2_100, 12_000).navAssistControlAllowed)
        }
    }

    @Test fun `built client permits normal two second observations but expires longer gaps`() {
        val gate = NavigationSourceGate(com.garan.tesnav.BuildConfig.NAV_ASSIST_SOURCE_BUDGET_MS,
            com.garan.tesnav.BuildConfig.NAV_ASSIST_PROGRESS_BUDGET_MS).apply { arm(100) }
        assertTrue(gate.prepare(state(), 2_325, 12_225).navAssistControlAllowed)
        assertFalse(gate.prepare(state(), 3_101, 13_001).navAssistControlAllowed)
    }

    @Test fun `same event recovers after stable fresh observations without explicit rearm`() {
        val gate = gate()
        assertTrue(gate.prepare(state(), 100, 10_000).navAssistControlAllowed)
        assertFalse(gate.prepare(state().copy(gpsSignalWeak = true), 200, 10_100).navAssistControlAllowed)
        val fresh = state().copy(locationObservedAtMs = 12_000, guidanceObservedAtMs = 12_000,
            locationReceivedElapsedMs = 2_100, guidanceReceivedElapsedMs = 2_100)
        assertFalse(gate.prepare(fresh, 2_100, 12_000).navAssistControlAllowed)
        assertFalse(gate.prepare(fresh, 3_100, 13_000).navAssistControlAllowed)
        assertTrue(gate.prepare(fresh.copy(locationObservedAtMs = 13_000,
            locationReceivedElapsedMs = 3_100), 3_100, 13_000).navAssistControlAllowed)
    }

    @Test fun `a second source failure resets recovery stability`() {
        val gate = gate()
        gate.prepare(state(), 100, 10_000)
        gate.prepare(state().copy(gpsSignalWeak = true), 200, 10_100)
        val fresh = state().copy(locationObservedAtMs = 12_000, guidanceObservedAtMs = 12_000,
            locationReceivedElapsedMs = 2_100, guidanceReceivedElapsedMs = 2_100)
        gate.prepare(fresh, 2_100, 12_000)
        gate.prepare(fresh.copy(gpsSignalWeak = true), 2_500, 12_400)
        val next = fresh.copy(locationObservedAtMs = 13_000, locationReceivedElapsedMs = 3_100)
        assertFalse(gate.prepare(next, 3_100, 13_000).navAssistControlAllowed)
        assertFalse(gate.prepare(next, 3_900, 13_800).navAssistControlAllowed)
    }

    @Test fun `zero distance recovers with unchanged matched guidance and fresh locations`() {
        val gate = NavigationSourceGate(3_000, 6_000).apply { arm(100) }
        val stopped = state().copy(speedKph = 0f, nextTurnDistanceMeters = 0)
        assertTrue(gate.prepare(stopped, 100, 10_000).navAssistControlAllowed)
        assertFalse(gate.prepare(stopped, 3_101, 13_001).navAssistControlAllowed)
        assertEquals("sourceStalled", gate.reason)
        val fresh = stopped.copy(speedKph = 0.288f, locationObservedAtMs = 20_000,
            locationReceivedElapsedMs = 10_100, guidanceCallbackElapsedMs = 10_100)
        assertFalse(gate.prepare(fresh, 10_100, 20_000).navAssistControlAllowed)
        assertEquals("awaitingSourceRecovery", gate.reason)
        assertFalse(gate.prepare(fresh, 11_100, 21_000).navAssistControlAllowed)
        val recovered = fresh.copy(locationObservedAtMs = 21_000,
            locationReceivedElapsedMs = 11_100, guidanceCallbackElapsedMs = 11_100)
        assertTrue(gate.prepare(recovered, 11_100, 21_000).navAssistControlAllowed)
        // Callback delivery must not rewrite actual guidance progress.
        assertEquals(100L, recovered.guidanceReceivedElapsedMs)
        assertEquals(10_000L, recovered.guidanceObservedAtMs)
        assertFalse(gate.prepare(recovered, 14_101, 24_001).navAssistControlAllowed)
        assertEquals("sourceStalled", gate.reason)
    }

    @Test fun `near zero tolerance requires fresh guidance and never hides moving stalled progress`() {
        val fresh = state().copy(locationObservedAtMs = 20_000, locationReceivedElapsedMs = 10_100,
            guidanceCallbackElapsedMs = 10_100)
        for (speed in listOf(0f, 0.288f, 0.396f, 0.5f)) {
            assertTrue(gate().prepare(fresh.copy(speedKph = speed), 10_100, 20_000).navAssistControlAllowed)
            assertFalse(gate().prepare(fresh.copy(speedKph = speed,
                guidanceCallbackElapsedMs = 9_099), 10_100, 20_000).navAssistControlAllowed)
        }
        for (speed in listOf(0.501f, 1f, 60f, Float.NaN, Float.POSITIVE_INFINITY, -1f)) {
            assertFalse(gate().prepare(fresh.copy(speedKph = speed), 10_100, 20_000).navAssistControlAllowed)
        }
        for (bad in listOf(fresh.copy(speedKph = 0f, guidancePathId = 8),
            fresh.copy(speedKph = 0f, guidanceStepIndex = 3),
            fresh.copy(speedKph = 0f, guidanceCallbackElapsedMs = 10_101),
            fresh.copy(speedKph = 0f, gpsSignalWeak = true))) {
            assertFalse(gate().prepare(bad, 10_100, 20_000).navAssistControlAllowed)
        }
    }
}
