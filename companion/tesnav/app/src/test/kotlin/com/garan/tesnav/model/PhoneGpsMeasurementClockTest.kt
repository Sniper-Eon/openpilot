package com.garan.tesnav.model

import org.junit.Assert.*
import org.junit.Test

class PhoneGpsMeasurementClockTest {
    @Test fun `fresh GPS uses physical elapsed timestamp despite GNSS wall skew`() {
        // A GPS UTC time 1.2 s ahead is deliberately not the freshness clock.
        assertEquals(9_950L, phoneGpsLocalMeasurementTime(10_000, 5_000, 4_950))
    }
    @Test fun `redelivery never renews the measurement timestamp`() {
        val first = phoneGpsLocalMeasurementTime(10_000, 5_000, 4_950)
        assertEquals(first, phoneGpsLocalMeasurementTime(12_000, 7_000, 4_950))
        assertNull(phoneGpsLocalMeasurementTime(13_000, 8_000, 4_950))
    }
    @Test fun `future and invalid monotonic measurements are rejected`() {
        assertNull(phoneGpsLocalMeasurementTime(10_000, 5_000, 5_001))
        assertNull(phoneGpsLocalMeasurementTime(10_000, 5_000, -1))
        assertNull(phoneGpsLocalMeasurementTime(-1, 5_000, 4_950))
    }
    @Test fun `three second expiry boundary remains strict`() {
        assertEquals(7_001L, phoneGpsLocalMeasurementTime(10_000, 5_000, 2_001))
        assertNull(phoneGpsLocalMeasurementTime(10_000, 5_000, 2_000))
    }
}
