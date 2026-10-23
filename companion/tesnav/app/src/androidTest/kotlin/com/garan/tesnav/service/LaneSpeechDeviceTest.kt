package com.garan.tesnav.service

import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.garan.tesnav.export.LaneAnnouncement
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** No navigation service, network request, lamp, or vehicle-control interface is used. */
@RunWith(AndroidJUnit4::class)
class LaneSpeechDeviceTest {
    @Test fun actualChinesePlaybackCompletesOnceAndMutedOrCancelledDoesNot() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val receipts = LinkedBlockingQueue<String>()
        var enabled = true
        lateinit var speech: LaneChangeSpeech
        instrumentation.runOnMainSync {
            speech = LaneChangeSpeech(instrumentation.targetContext, { enabled }) { id, session ->
                receipts.add("$session:$id")
            }
        }
        fun offer(id: String, side: String) = instrumentation.runOnMainSync {
            speech.offer(LaneAnnouncement(id, "isolated-device-test", side, SystemClock.elapsedRealtime()))
        }
        try {
            for ((id, side) in listOf("a".repeat(32) to "left", "b".repeat(32) to "right")) {
                val deadline = SystemClock.elapsedRealtime() + 15_000
                var receipt: String? = null
                while (SystemClock.elapsedRealtime() < deadline && receipt == null) {
                    offer(id, side)
                    receipt = receipts.poll(150, TimeUnit.MILLISECONDS)
                }
                assertEquals("Chinese $side playback did not complete (check TTS/volume/audio focus)",
                    "isolated-device-test:$id", receipt)
                repeat(8) { offer(id, side); SystemClock.sleep(100) }
                assertNull("Repeated feedback must not repeat completion", receipts.poll())
                instrumentation.runOnMainSync { speech.offer(null) }
            }
            instrumentation.runOnMainSync { enabled = false }
            repeat(15) { offer("c".repeat(32), "left"); SystemClock.sleep(100) }
            assertNull("Muted request produced completion", receipts.poll())
            instrumentation.runOnMainSync {
                enabled = true
                speech.offer(LaneAnnouncement("d".repeat(32), "isolated-device-test", "right", SystemClock.elapsedRealtime()))
                speech.cancel()
            }
            assertNull("Cancelled request produced completion", receipts.poll(2, TimeUnit.SECONDS))
        } finally { instrumentation.runOnMainSync { speech.close() } }
    }
}
