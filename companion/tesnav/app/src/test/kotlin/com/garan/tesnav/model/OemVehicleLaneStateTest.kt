package com.garan.tesnav.model

import com.garan.tesnav.ui.LaneGuidancePresenter
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class OemVehicleLaneStateTest {
    @Test
    fun `receipt expires at the display deadline even if wall clock moves backwards`() {
        val state = feedback().copy(receivedAtMs = Long.MAX_VALUE)
        assertEquals(1L, state.remainingDisplayMs(1_549L, 550L))
        assertSame(state, state.forDisplay(1_549L, 550L))
        assertEquals(OemVehicleLaneState(receivedAtMs = Long.MAX_VALUE), state.forDisplay(1_550L, 550L))
        assertFalse(state.copy(receivedAtMs = 1L).forDisplay(1_551L, 550L).permissionValid)
    }

    @Test
    fun `missing future negative or expired receipt cannot display valid feedback`() {
        for (received in listOf(null, -1L, 1_001L, 0L)) {
            val state = feedback().copy(receivedAtElapsedMs = received)
            assertEquals(0L, state.remainingDisplayMs(1_000L, 550L))
            assertEquals(OemVehicleLaneState(receivedAtMs = state.receivedAtMs), state.forDisplay(1_000L, 550L))
        }
        assertEquals(0L, feedback().remainingDisplayMs(1_000L, 0L))
        assertEquals(0L, feedback().remainingDisplayMs(1_000L, -1L))
        assertEquals(550L, feedback().copy(receivedAtElapsedMs = 0L).remainingDisplayMs(0L, 550L))
    }

    @Test
    fun `expired feedback leaves route arrows but reports unknown OEM state`() {
        val presentation = LaneGuidancePresenter.present(
            NavigationState(
                navigationMode = NavigationMode.REALTIME,
                navAssistSourceStatus = "healthy",
                unkeyedRouteFactsConfirmed = true,
                lanes = listOf(
                    LaneState(index = 0, recommended = true, allowedActions = listOf(LaneAction.LEFT)),
                    LaneState(index = 1, allowedActions = listOf(LaneAction.STRAIGHT)),
                ),
            ),
            feedback().forDisplay(1_550L, 550L),
        )!!
        assertEquals("←", presentation.items.first().symbols)
        assertTrue(presentation.title.contains("路线建议靠左"))
        assertTrue(presentation.title.contains("车道未知"))
        assertTrue(presentation.title.contains("许可未知"))
        assertFalse(presentation.title.contains("原车报告左侧许可"))
    }

    @Test
    fun `silent source expires without navigation updates or another ACK`() = runBlocking {
        val now = AtomicLong(1_000L)
        val source = MutableStateFlow(feedback())
        val events = Channel<OemVehicleLaneState>(Channel.UNLIMITED)
        val job = launch { source.withDisplayExpiry(40L, now::get).collect { events.send(it) } }
        try {
            assertTrue(withTimeout(2_000L) { events.receive() }.permissionValid)
            now.set(1_040L)
            assertFalse(withTimeout(2_000L) { events.receive() }.permissionValid)
            assertTrue(source.value.permissionValid) // Display expiry must not mutate Service data.
        } finally {
            job.cancelAndJoin()
            events.close()
        }
    }

    @Test
    fun `new receipt cancels previous deadline and only expires on its own deadline`() = runBlocking {
        val now = AtomicLong(1_000L)
        val source = MutableStateFlow(feedback())
        val events = Channel<OemVehicleLaneState>(Channel.UNLIMITED)
        val job = launch { source.withDisplayExpiry(40L, now::get).collect { events.send(it) } }
        try {
            assertTrue(withTimeout(2_000L) { events.receive() }.permissionValid)
            now.set(1_030L)
            source.value = feedback().copy(receivedAtElapsedMs = 1_030L, rightAllowed = true)
            assertTrue(withTimeout(2_000L) { events.receive() }.rightAllowed)
            now.set(1_040L)
            assertNull(withTimeoutOrNull(80L) { events.receive() })
            now.set(1_070L)
            assertFalse(withTimeout(2_000L) { events.receive() }.permissionValid)
        } finally {
            job.cancelAndJoin()
            events.close()
        }
    }

    @Test
    fun `resubscription after sleep never emits cached permission as valid`() = runBlocking {
        val source = MutableStateFlow(feedback())
        val events = Channel<OemVehicleLaneState>(Channel.UNLIMITED)
        val job = launch { source.withDisplayExpiry(550L) { 10_000L }.collect { events.send(it) } }
        try {
            assertFalse(withTimeout(2_000L) { events.receive() }.permissionValid)
            assertNull(withTimeoutOrNull(40L) { events.receive() })
        } finally {
            job.cancelAndJoin()
            events.close()
        }
    }

    @Test
    fun `wall timestamp changes do not renew the monotonic receipt`() = runBlocking {
        val now = AtomicLong(1_000L)
        val source = MutableStateFlow(feedback())
        val events = Channel<OemVehicleLaneState>(Channel.UNLIMITED)
        val job = launch { source.withDisplayExpiry(40L, now::get).collect { events.send(it) } }
        try {
            assertTrue(withTimeout(2_000L) { events.receive() }.permissionValid)
            now.set(1_040L)
            source.value = source.value.copy(receivedAtMs = 999_999L)
            assertFalse(withTimeout(2_000L) { events.receive() }.permissionValid)
            job.cancelAndJoin()
            while (events.tryReceive().isSuccess) { /* Drain already delivered events. */ }
            source.value = feedback().copy(receivedAtElapsedMs = 1_040L)
            assertNull(withTimeoutOrNull(80L) { events.receive() })
        } finally {
            job.cancelAndJoin()
            events.close()
        }
    }

    private fun feedback() = OemVehicleLaneState(
        position = OemLanePosition.MIDDLE,
        positionValid = true,
        permissionValid = true,
        leftAllowed = true,
        blindspotValid = true,
        radarValid = true,
        vehicleStateValid = true,
        leadPresent = true,
        leadDistanceM = 30f,
        receivedAtMs = 123_456L,
        receivedAtElapsedMs = 1_000L,
    )
}
