package com.garan.tesnav.model

import org.junit.Assert.*
import org.junit.Test

class IndependentPlanningOriginTest {
    private val real = NavigationLocationObservation("phone-gps", 10_000, 100, 0,
        32.4563, 119.9097, 4.9, null, null, NavigationCoordinateSystem.GCJ02, true)

    @Test fun `physical position is usable without motion or route matching`() {
        assertEquals(GeoPoint(real.latitude, real.longitude), independentPlanningOrigin(real, 101, 10_001))
    }

    @Test fun `navigator or injected coordinates cannot replace independent GPS`() {
        for (source in listOf("phone-sdk", "vehicle-can", "")) {
            assertNull(independentPlanningOrigin(real.copy(sourceEpoch = source, latitude = 32.443), 101, 10_001))
        }
        assertNull(independentPlanningOrigin(null, 101, 10_001))
        assertNull(independentPlanningOrigin(real.copy(coordinateSystem = NavigationCoordinateSystem.WGS84), 101, 10_001))
        assertNull(independentPlanningOrigin(real.copy(measurementTimeVerified = false), 101, 10_001))
    }

    @Test fun `holding a pre simulation fix cannot renew its observation lifetime`() {
        assertNotNull(independentPlanningOrigin(real, 3099, 12_999))
        assertNull(independentPlanningOrigin(real, 3100, 13_000))
        assertNull(independentPlanningOrigin(real.copy(receivedElapsedMs = 3100), 3100, 13_000))
        assertNull(independentPlanningOrigin(real.copy(ageAtReceiptMs = 2000), 1100, 11_000))
        val recovered = real.copy(measuredAtMs = 13_000, receivedElapsedMs = 3100, latitude = 32.457)
        assertEquals(GeoPoint(32.457, real.longitude), independentPlanningOrigin(recovered, 3101, 13_001))
    }

    @Test fun `clock reversal and invalid physical observations are rejected`() {
        for (fix in listOf(real.copy(measuredAtMs = 10_002), real.copy(receivedElapsedMs = 102),
            real.copy(ageAtReceiptMs = -1), real.copy(latitude = Double.NaN),
            real.copy(longitude = 181.0), real.copy(accuracyM = 0.0), real.copy(accuracyM = null))) {
            assertNull(independentPlanningOrigin(fix, 101, 10_001))
        }
    }
}
