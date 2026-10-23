package com.garan.tesnav.model

import org.junit.Assert.*
import org.junit.Test

class NavigationLocationFallbackTest {
    private fun fix(t: Long = 100) = NavigationLocationObservation("epoch", 10_000 + t, t, 0,
        32.0, 121.0, 5.0, 0.0, 90.0, NavigationCoordinateSystem.GCJ02, true)
    private fun NavigationLocationFallback.at(t: Long, phone: NavigationLocationObservation?,
        vehicle: NavigationLocationObservation?, active: Boolean = true) = select(phone, vehicle, active, t, 10_000 + t)

    @Test fun `vehicle preferred then phone used when vehicle expires`() {
        val s = NavigationLocationFallback()
        assertEquals(NavigationLocationSource.VEHICLE, s.at(100, fix(), fix()).source)
        val fallback = s.at(3100, fix(), fix(3100))
        assertEquals(NavigationLocationSource.VEHICLE, fallback.source)
        assertNotNull(fallback.vehicleFixToInject)
        assertNull(s.at(3200, null, fix(3100).copy(receivedElapsedMs = 3200)).vehicleFixToInject)
        assertNotNull(s.at(4100, null, fix(4100)).vehicleFixToInject)
        assertEquals(NavigationLocationSource.NONE, s.at(7100, null, fix(4100)).source)
    }

    @Test fun `phone is used immediately when vehicle is unavailable`() {
        val s = NavigationLocationFallback()
        s.at(100, null, fix())
        assertEquals(NavigationLocationSource.VEHICLE, s.at(1100, fix(1100), fix(1100)).source)
        assertEquals(NavigationLocationSource.PHONE, s.at(2100, fix(2100), null).source)
        assertEquals(NavigationLocationSource.PHONE, s.at(3100, fix(1100), null).source)
        assertEquals(NavigationLocationSource.PHONE, s.at(3100, fix(3100), null).source)
    }

    @Test fun `unverified and invalid vehicle observations never become fallback`() {
        val f = fix()
        for (bad in listOf(f.copy(measurementTimeVerified = false), f.copy(accuracyM = null),
            f.copy(accuracyM = 51.0), f.copy(accuracyM = Double.NaN), f.copy(speedMps = null),
            f.copy(speedMps = -1.0), f.copy(bearingDeg = 360.0), f.copy(latitude = 91.0),
            f.copy(longitude = Double.NaN), f.copy(coordinateSystem = NavigationCoordinateSystem.UNKNOWN),
            f.copy(measuredAtMs = 10_101), f.copy(receivedElapsedMs = 101), f.copy(ageAtReceiptMs = 3000),
            f.copy(sourceEpoch = ""))) {
            assertEquals(NavigationLocationSource.NONE, NavigationLocationFallback().at(100, null, bad).source)
        }
    }

    @Test fun `transport age cannot be refreshed by changing receipt or advancing heartbeat`() {
        val s = NavigationLocationFallback()
        assertEquals(NavigationLocationSource.VEHICLE, s.at(100, null, fix().copy(ageAtReceiptMs = 2000)).source)
        assertEquals(NavigationLocationSource.NONE, s.at(1100, null, fix().copy(ageAtReceiptMs = 2000)).source)
        assertEquals(NavigationLocationSource.NONE, s.at(3100, null, fix().copy(receivedElapsedMs = 3100)).source)
    }

    @Test fun `stop reset clock reversal and vehicle timestamp reversal fail closed`() {
        val s = NavigationLocationFallback()
        s.at(200, null, fix(200))
        assertEquals("vehicleTimeReversed", s.at(201, null, fix(100)).reason)
        assertEquals("clockInvalid", s.at(199, null, fix(199)).reason)
        assertEquals("inactive", s.at(300, fix(300), fix(300), active = false).reason)
        assertEquals(NavigationLocationSource.PHONE, s.at(301, fix(301), null).source)
    }

    @Test fun `fresh vehicle remains primary while phone changes`() {
        val s = NavigationLocationFallback()
        s.at(100, null, fix())
        s.at(1000, fix(1000), fix(1000))
        s.at(2000, null, fix(2000))
        assertEquals(NavigationLocationSource.VEHICLE, s.at(3000, fix(3000), fix(3000)).source)
        assertEquals(NavigationLocationSource.VEHICLE, s.at(4000, fix(4000), fix(4000)).source)
        assertEquals(NavigationLocationSource.VEHICLE, s.at(5000, fix(5000), fix(5000)).source)
    }
}
