package com.garan.tesnav.data

import org.junit.Assert.*
import org.junit.Test

class RouteRequestAssociationTest {
    @Test fun `unkeyed route facts require current keyed guidance and are revoked on route changes`() {
        val confirmed = com.garan.tesnav.model.NavigationState(
            routePlanned = true, acceptedPathId = 42L, guidancePathId = 42L,
            unkeyedRouteFactsConfirmed = true,
        )
        assertTrue(confirmed.acceptsUnkeyedRouteFacts(42L))
        assertFalse(confirmed.copy(unkeyedRouteFactsConfirmed = false).acceptsUnkeyedRouteFacts(42L))
        assertFalse(confirmed.copy(routePlanned = false).acceptsUnkeyedRouteFacts(42L))
        assertFalse(confirmed.copy(routeRecalculating = true).acceptsUnkeyedRouteFacts(42L))
        assertFalse(confirmed.copy(guidancePathId = null).acceptsUnkeyedRouteFacts(42L))
        assertFalse(confirmed.copy(acceptedPathId = 43L).acceptsUnkeyedRouteFacts(43L))
        assertFalse(confirmed.acceptsUnkeyedRouteFacts(43L))
        assertFalse(confirmed.acceptsUnkeyedRouteFacts(null))
        assertTrue(confirmed.copy(acceptedPathId = 43L, guidancePathId = 43L).acceptsUnkeyedRouteFacts(43L))
    }

    @Test fun `lane callback is bound only after keyed guidance confirms the installed path`() {
        assertEquals(42L, confirmedLanePath(42L, 42L, 42L, false))
        assertNull(confirmedLanePath(42L, null, 42L, false))
        assertNull(confirmedLanePath(42L, 41L, 42L, false))
        assertNull(confirmedLanePath(42L, 42L, 41L, false))
        assertNull(confirmedLanePath(42L, 42L, 42L, true))
    }

    @Test fun `reroute needs new installed path and unchanged destination`() {
        val end = com.garan.tesnav.model.GeoPoint(31.0, 121.0)
        assertTrue(recalculatedRouteMatches(100, 101, 101, end, end))
        assertFalse(recalculatedRouteMatches(100, 100, 100, end, end))
        assertFalse(recalculatedRouteMatches(100, 101, 102, end, end))
        assertFalse(recalculatedRouteMatches(null, 101, 101, end, end))
        assertFalse(recalculatedRouteMatches(100, 101, 101, end, null))
        assertFalse(recalculatedRouteMatches(100, 101, 101, end, end.copy(latitude = 32.0)))
        assertFalse(recalculatedRouteMatches(100, 101, 101, end, end.copy(latitude = Double.NaN)))
        assertFalse(recalculatedRouteMatches(100, 0, 0, end, end))
    }

    @Test fun `missing terminal callback quarantines retries instead of repeatedly queuing`() {
        val gate = RouteRequestAssociation()
        val token = requireNotNull(gate.begin())
        assertTrue(gate.startCall(token))
        assertTrue(gate.timeout(token))
        assertTrue(gate.recoveryRequired)
        repeat(3) {
            gate.invalidate()
            assertNull(gate.begin())
        }
        assertFalse(gate.resetEngine(false))
        assertTrue(gate.recoveryRequired)
        assertNull(gate.begin())
        assertTrue(gate.resetEngine(true))
        assertFalse(gate.recoveryRequired)
        assertTrue(gate.startCall(requireNotNull(gate.begin())))
    }

    @Test fun `late terminal callback restores planning without accepting the expired result`() {
        val gate = RouteRequestAssociation()
        val token = requireNotNull(gate.begin())
        assertTrue(gate.startCall(token))
        assertTrue(gate.timeout(token))
        assertTrue(gate.completeCall(token))
        assertFalse(gate.finishCall(token))
        assertFalse(gate.recoveryRequired)
        assertTrue(gate.startCall(requireNotNull(gate.begin())))
    }

    @Test fun `refused SDK destruction preserves cancelled call occupancy across rebinding`() {
        val gate = RouteRequestAssociation()
        val old = requireNotNull(gate.begin())
        assertTrue(gate.startCall(old))
        gate.invalidate()
        assertFalse(gate.resetEngine(false))
        val next = requireNotNull(gate.begin())
        assertFalse(gate.startCall(next))
        assertTrue(gate.completeCall(old))
        assertFalse(gate.finishCall(old))
        assertTrue(gate.startCall(next))
    }

    @Test fun `cancelled SDK call drains before its replacement starts`() {
        val gate = RouteRequestAssociation()
        val old = requireNotNull(gate.begin())
        assertTrue(gate.startCall(old))
        gate.invalidate()
        val next = requireNotNull(gate.begin())
        assertFalse(gate.startCall(next))
        assertTrue(gate.completeCall(old))
        assertFalse(gate.finishCall(old))
        assertTrue(gate.isPending(next))
        assertTrue(gate.startCall(next))
        assertFalse(gate.completeCall(old))
        assertFalse(gate.startCall(next))
        assertTrue(gate.completeCall(next))
        assertTrue(gate.finishCall(next))
    }

    @Test fun `timeout or stop while queued never starts cancelled work`() {
        val gate = RouteRequestAssociation()
        val old = requireNotNull(gate.begin())
        assertTrue(gate.startCall(old))
        assertTrue(gate.failInvocation(old))
        val waiting = requireNotNull(gate.begin())
        assertFalse(gate.startCall(waiting))
        assertTrue(gate.failInvocation(waiting))
        assertTrue(gate.completeCall(old))
        assertFalse(gate.startCall(waiting))
        val latest = requireNotNull(gate.begin())
        assertTrue(gate.startCall(latest))
    }

    @Test fun `engine reset clears SDK occupancy but old completion cannot clear new call`() {
        val gate = RouteRequestAssociation()
        val old = requireNotNull(gate.begin())
        assertTrue(gate.startCall(old))
        gate.resetEngine(true)
        val current = requireNotNull(gate.begin())
        assertTrue(gate.startCall(current))
        assertFalse(gate.completeCall(old))
        assertFalse(gate.finishCall(old))
        assertTrue(gate.completeCall(current))
        assertTrue(gate.finishCall(current))
    }

    @Test fun `independent listener owns its call even before invoke ID delivery`() {
        val gate = RouteRequestAssociation()
        val token = requireNotNull(gate.begin())
        assertTrue(gate.finishCall(token))
        assertFalse(gate.finishCall(token))
        gate.bind(token, 101)
        assertFalse(gate.matches(101))
        assertNotNull(gate.begin())
    }

    @Test fun `stopped or timed out independent listener cannot finish new request`() {
        val gate = RouteRequestAssociation()
        val old = requireNotNull(gate.begin())
        gate.bind(old, 101)
        assertTrue(gate.failInvocation(old))
        val current = requireNotNull(gate.begin())
        assertFalse(gate.finishCall(old))
        assertFalse(gate.failInvocation(old))
        assertTrue(gate.finishCall(current))
    }

    @Test fun `global result zero cannot complete call with invocation ID 101`() {
        val gate = RouteRequestAssociation()
        val token = requireNotNull(gate.begin())
        gate.bind(token, 101)
        assertFalse(gate.finish(0))
        assertTrue(gate.finishCall(token))
        assertFalse(gate.failInvocation(token))
    }

    @Test fun `guidance requires the accepted path in both callback and engine`() {
        assertTrue(routeObservationMatches(7, 7, 7))
        for (ids in listOf(Triple(null, 7L, 7L), Triple(7L, 8L, 7L), Triple(7L, 7L, 8L), Triple(0L, 0L, 0L))) {
            assertFalse(routeObservationMatches(ids.first, ids.second, ids.third))
        }
    }
    @Test fun `pending request is serialized and unbound results cannot win`() {
        val gate = RouteRequestAssociation()
        val token = requireNotNull(gate.begin())
        assertNull(gate.begin())
        assertFalse(gate.finish(42))
        gate.bind(token, 42)
        assertFalse(gate.finish(41))
        assertTrue(gate.finish(42))
        assertFalse(gate.finish(42))
    }

    @Test fun `stop and new request reject old binding success and failure`() {
        val gate = RouteRequestAssociation()
        val old = requireNotNull(gate.begin())
        gate.bind(old, 11)
        gate.invalidate()
        val current = requireNotNull(gate.begin())
        gate.bind(old, 11)
        assertFalse(gate.matches(11))
        gate.bind(current, 22)
        assertFalse(gate.finish(11))
        assertTrue(gate.finish(22))
    }

    @Test fun `missing and invalid request IDs never confirm a route`() {
        val gate = RouteRequestAssociation()
        val token = requireNotNull(gate.begin())
        for (id in listOf(-1, 0)) {
            gate.bind(token, id)
            assertFalse(gate.matches(id))
        }
        assertFalse(gate.matches(null))
        gate.invalidate()
        assertNotNull(gate.begin())
    }

    @Test fun `invocation failure clears only its own pending request`() {
        val gate = RouteRequestAssociation()
        val old = requireNotNull(gate.begin())
        assertTrue(gate.failInvocation(old))
        val current = requireNotNull(gate.begin())
        assertFalse(gate.failInvocation(old))
        gate.bind(current, 12)
        assertTrue(gate.finish(12))
    }
}
