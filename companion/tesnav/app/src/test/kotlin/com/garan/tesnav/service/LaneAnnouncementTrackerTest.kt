package com.garan.tesnav.service

import com.garan.tesnav.export.LaneAnnouncement
import org.junit.Assert.*
import org.junit.Test

class LaneAnnouncementTrackerTest {
    private fun request(id: String = "a".repeat(32), direction: String = "left", time: Long = 100L) =
        LaneAnnouncement(id, "session", direction, time)

    @Test fun `only matching started and completed utterance produces receipt once`() {
        val t = LaneAnnouncementTracker(); val r = request()
        assertEquals("准备向左变道", t.offer(r, true, 100))
        assertNull(t.onDone(r.id, true, 110)) // Queued is not played.
        t.onStart(r.id, 120)
        assertNull(t.onDone("wrong", true, 130))
        assertEquals(r, t.onDone(r.id, true, 140))
        assertNull(t.onDone(r.id, true, 150))
        assertNull(t.offer(r, true, 160))
    }

    @Test fun `cancel mute stale and session change discard late callbacks`() {
        for (fault in listOf("cancel", "mute", "stale", "replace")) {
            val t = LaneAnnouncementTracker(); val r = request()
            t.offer(r, true, 100); t.onStart(r.id, 120)
            when (fault) {
                "cancel" -> t.cancel()
                "mute" -> t.offer(r, false, 130)
                "stale" -> t.offer(r, true, 1_200)
                "replace" -> t.offer(request("b".repeat(32), "right").copy(sessionId="new"), true, 130)
            }
            assertNull(t.onDone(r.id, true, 140))
            assertNull(t.offer(r, true, 150))
        }
    }

    @Test fun `continuous fresh feedback cannot extend speech deadline`() {
        val t = LaneAnnouncementTracker(); val r = request()
        t.offer(r, true, 100); t.onStart(r.id, 120)
        for (now in 200L..8_000L step 200) assertNull(t.offer(r.copy(receivedAtElapsedMs=now), true, now))
        assertNull(t.onDone(r.id, true, 8_101))
    }

    @Test fun `right request uses right prompt and requires audible completion`() {
        val t = LaneAnnouncementTracker(); val r = request(direction="right")
        assertNull(t.offer(r, false, 100))
        assertEquals("准备向右变道", t.offer(r, true, 100))
        t.onStart(r.id, 110)
        assertNull(t.onDone(r.id, false, 120))
    }
}
