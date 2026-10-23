package com.garan.tesnav.config

import org.junit.Assert.assertEquals
import org.junit.Test

class SpeechModeTest {
    @Test fun modesMatchAmapValuesAndUnknownFallsBackToConcise() {
        assertEquals(SpeechMode.CONCISE, SpeechMode.fromValue(1))
        assertEquals(SpeechMode.DETAILED, SpeechMode.fromValue(2))
        assertEquals(SpeechMode.MUTED, SpeechMode.fromValue(0))
        assertEquals(SpeechMode.CONCISE, SpeechMode.fromValue(-1))
        assertEquals(SpeechMode.CONCISE, SpeechMode.fromValue(999))
    }
}
