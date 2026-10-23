package com.garan.tesnav.model

import org.junit.Assert.*
import org.junit.Test

class NavigationExternalLocationControllerTest {
    @Test fun `fresh phone callbacks cannot prevent fallback while phone satellites are weak`() {
        val sink = Sink(); val c = NavigationExternalLocationController(sink)
        assertEquals(NavigationLocationSource.VEHICLE, c.update(fix(100), fix(100), true, 100, 10100).source)
        assertEquals(NavigationLocationSource.VEHICLE,
            c.update(fix(200), fix(200), true, 200, 10200, phoneSignalWeak=true).source)
        assertEquals(listOf("enable:true", "fix:10100", "fix:10200"), sink.calls)
    }
    @Test fun `vehicle remains primary regardless of phone weak callback`() {
        val c = NavigationExternalLocationController(Sink())
        c.update(fix(100), fix(100), true, 100, 10100, phoneSignalWeak=true)
        assertEquals(NavigationLocationSource.VEHICLE,
            c.update(fix(3100), fix(3100), true, 3100, 13100, phoneSignalWeak=true).source)
        assertEquals(NavigationLocationSource.VEHICLE,
            c.update(fix(3200), fix(3200), true, 3200, 13200, phoneSignalWeak=false).source)
        assertEquals(NavigationLocationSource.VEHICLE,
            c.update(fix(5200), fix(5200), true, 5200, 15200, phoneSignalWeak=false).source)
    }
    @Test fun `phone weak state cannot poison vehicle or clear absent vehicle data`() {
        assertTrue(selectedLocationWeak(false, false, true))
        assertFalse(selectedLocationWeak(false, false, false))
        assertFalse(selectedLocationWeak(true, true, true))
        assertTrue(selectedLocationWeak(true, false, false))
        assertTrue(selectedLocationWeak(true, false, true))
    }
    @Test fun `weak phone with absent or expired vehicle remains unavailable`() {
        val c = NavigationExternalLocationController(Sink())
        assertEquals(NavigationLocationSource.NONE,
            c.update(fix(100), null, true, 100, 10100, phoneSignalWeak=true).source)
        c.update(fix(200), fix(200), true, 200, 10200, phoneSignalWeak=true)
        assertEquals(NavigationLocationSource.NONE,
            c.update(fix(3200), fix(200), true, 3200, 13200, phoneSignalWeak=true).source)
        assertFalse(c.isExternalEnabled)
    }
    private fun fix(t: Long) = NavigationLocationObservation("test", 10_000+t, t, 0,
        32.0, 121.0, 5.0, 0.0, 90.0, NavigationCoordinateSystem.GCJ02, true)
    private class Sink : NavigationExternalLocationSink {
        val calls = mutableListOf<String>()
        var failInject = false
        var failDisable = false
        override fun setExternalEnabled(enabled: Boolean) {
            calls.add("enable:$enabled")
            if (!enabled && failDisable) error("disable failed")
        }
        override fun inject(fix: NavigationLocationObservation) {
            calls.add("fix:${fix.measuredAtMs}")
            if (failInject) error("injection failed")
        }
    }
    @Test fun `qualified fallback enables before injection and does not resend duplicate samples`() {
        val sink = Sink(); val c = NavigationExternalLocationController(sink)
        assertEquals(NavigationLocationSource.VEHICLE, c.update(null, fix(100), true, 100, 10100).source)
        c.update(null, fix(100), true, 200, 10200)
        assertEquals(listOf("enable:true", "fix:10100"), sink.calls)
        assertEquals(10100L, c.injectedFix!!.measuredAtMs)
        c.update(null, null, true, 3100, 13100)
        assertEquals("enable:false", sink.calls.last())
        assertNull(c.injectedFix)
    }
    @Test fun `phone fallback disables external mode and stop resets it`() {
        val sink = Sink(); val c = NavigationExternalLocationController(sink)
        c.update(null, fix(100), true, 100, 10100)
        c.update(fix(1100), fix(1100), true, 1100, 11100)
        assertEquals(NavigationLocationSource.PHONE, c.update(fix(3100), null, true, 3100, 13100).source)
        assertEquals("enable:false", sink.calls.last())
        c.update(null, fix(6100), true, 6100, 16100)
        c.reset()
        assertEquals("enable:false", sink.calls.last())
    }
    @Test fun `unqualified raw telemetry cannot activate SDK`() {
        val sink = Sink(); val c = NavigationExternalLocationController(sink)
        c.update(null, fix(100).copy(measurementTimeVerified=false), true, 100, 10100)
        c.update(null, fix(100).copy(accuracyM=null), true, 100, 10100)
        c.update(null, fix(100), false, 100, 10100)
        assertTrue(sink.calls.isEmpty())
    }
    @Test fun `SDK exception fails closed and failed cleanup is retried`() {
        val sink = Sink().apply { failInject=true; failDisable=true }
        val c = NavigationExternalLocationController(sink)
        assertEquals("sdkLocationError", c.update(null, fix(100), true, 100, 10100).reason)
        assertNull(c.injectedFix)
        sink.failDisable=false
        assertTrue(c.isExternalEnabled)
        c.reset()
        assertFalse(c.isExternalEnabled)
        assertEquals(listOf("enable:true", "fix:10100", "enable:false", "enable:false"), sink.calls)
    }
}
