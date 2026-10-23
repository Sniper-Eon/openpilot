package com.garan.tesnav.service

import com.garan.tesnav.export.LaneAnnouncement

/** Correlates actual playback callbacks, never a queued/successful speak() call. */
internal class LaneAnnouncementTracker {
    var pending: LaneAnnouncement? = null
        private set
    private var started = false
    private var completed = false
    private var since = 0L
    private val attempted = linkedSetOf<String>()

    fun offer(request: LaneAnnouncement?, enabled: Boolean, now: Long): String? {
        if (!enabled || request == null || now - request.receivedAtElapsedMs !in 0L..1_000L) {
            cancel(); return null
        }
        if (pending?.id == request.id && pending?.sessionId == request.sessionId && pending?.direction == request.direction) {
            if (now - since > 8_000L) cancel() else pending = request
            return null
        }
        cancel()
        if (!attempted.add(request.id)) return null
        if (attempted.size > 128) attempted.remove(attempted.first())
        pending = request; since = now
        return if (request.direction == "left") "准备向左变道" else "准备向右变道"
    }

    fun onStart(id: String, now: Long) {
        if (valid(id, now)) started = true
    }

    fun onDone(id: String, enabled: Boolean, now: Long): LaneAnnouncement? {
        if (!enabled || !started || completed || !valid(id, now)) return null
        completed = true
        return pending
    }

    private fun valid(id: String, now: Long): Boolean = pending?.let {
        it.id == id && now - it.receivedAtElapsedMs in 0L..1_000L && now - since in 0L..8_000L
    } == true

    fun cancel() { pending = null; started = false; completed = false }
}
