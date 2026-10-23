package com.garan.tesnav.model

import org.junit.Assert.*
import org.junit.Test

class VehicleLocationObservationTest {
    @Test fun `missing telemetry preserves original deadline without granting new injection`() {
        val factory = VehicleLocationObservation()
        val original = factory.read(feedback(), 1000, 20000)!!
        assertSame(original, factory.read(OemVehicleLaneState(), 1500, 20500))
        assertSame(original, factory.read(feedback(2000).copy(navigationTelemetry=null), 2000, 21000))
        assertNotNull(factory.read(OemVehicleLaneState(), 3200, 22200))
        assertNull(factory.read(OemVehicleLaneState(), 3700, 22700))
    }
    @Test fun `explicit invalid telemetry clears cached fix so a missing ACK cannot revive it`() {
        val factory = VehicleLocationObservation()
        factory.read(feedback(), 1000, 20000)
        assertNull(factory.read(feedback(1200).copy(navigationTelemetry=telemetry().copy(gpsStatus="invalid")), 1200, 20200))
        assertNull(factory.read(OemVehicleLaneState(), 1300, 20300))
    }
    private fun telemetry(clock: Long = 10000) = OemNavigationTelemetry(
        gpsStatus = "observed", latitude = 32.0, longitude = 121.0, accuracyValue = 1.0,
        hdop = 1.0, headingDeg = 90.0, speedValue = 72.0, mapAvailable = null,
        controllerHealth = null, alcState = null, forkState = null, abortReason = null,
        navAvailable = null, navUsage = null, autosteerHealth = null, plannerState = null, navDistanceM = null,
        gpsTimeMs = clock, gpsTimeAgeMs = 100, gpsPositionAgeMs = 300, gpsMotionAgeMs = 50)
    private fun feedback(t: Long = 1000, clock: Long = 10000) = OemVehicleLaneState(
        receivedAtElapsedMs = t, navigationTelemetry = telemetry(clock))

    @Test fun `observation basis is explicit and oldest input age is retained`() {
        val fix = VehicleLocationObservation().read(feedback(), 1100, 20100)!!
        assertEquals(19700, fix.measuredAtMs)
        assertEquals(400, fix.ageAtReceiptMs)
        assertEquals(20.0, fix.speedMps!!, 0.0)
        assertFalse(fix.measurementTimeVerified)
        assertTrue(fix.observationTimeOnly)
    }
    @Test fun `repeated ACK never renews or reinjects observation`() {
        val factory = VehicleLocationObservation()
        val first = factory.read(feedback(), 1000, 20000)!!
        val repeated = factory.read(feedback(2000), 2000, 21000)!!
        assertSame(first, repeated)
        val selector = NavigationLocationFallback()
        assertNotNull(selector.select(null, first, true, 1000, 20000).vehicleFixToInject)
        assertNull(selector.select(null, repeated, true, 2000, 21000).vehicleFixToInject)
        assertEquals(NavigationLocationSource.NONE, selector.select(null, repeated, true, 4000, 23000).source)
    }
    @Test fun `stale disconnected invalid and old version feedback cannot inject`() {
        val factory = VehicleLocationObservation()
        assertNull(factory.read(OemVehicleLaneState(), 1000, 20000))
        assertNull(factory.read(feedback(), 3700, 22700))
        assertNull(factory.read(feedback().copy(navigationTelemetry = telemetry().copy(gpsPositionAgeMs = null)), 1000, 20000))
        assertNull(factory.read(feedback().copy(navigationTelemetry = telemetry().copy(gpsStatus = "jump")), 1000, 20000))
    }
    @Test fun `clock reversal rejected and stop resets epoch`() {
        val factory = VehicleLocationObservation()
        assertNotNull(factory.read(feedback(), 1000, 20000))
        assertNull(factory.read(feedback(2000, 9000), 2000, 21000))
        factory.reset()
        assertNotNull(factory.read(feedback(2000, 9000), 2000, 21000))
    }
    @Test fun `vehicle bridge keeps vehicle primary and falls back when it expires`() {
        val calls = mutableListOf<String>()
        val controller = NavigationExternalLocationController(object : NavigationExternalLocationSink {
            override fun setExternalEnabled(enabled: Boolean) { calls.add("enabled=$enabled") }
            override fun inject(fix: NavigationLocationObservation) { calls.add("inject") }
        })
        val factory = VehicleLocationObservation()
        val fix = factory.read(feedback(), 1000, 20000)!!
        assertEquals(NavigationLocationSource.VEHICLE, controller.update(null, fix, true, 1000, 20000).source)
        assertEquals(listOf("enabled=true", "inject"), calls)
        val phone = fix.copy(sourceEpoch="phone-gps", measuredAtMs=20000, ageAtReceiptMs=0,
            measurementTimeVerified=true, observationTimeOnly=false)
        assertEquals(NavigationLocationSource.VEHICLE, controller.update(phone, fix, true, 1000, 20000).source)
        assertEquals(NavigationLocationSource.PHONE, controller.update(phone.copy(measuredAtMs=24000, receivedElapsedMs=5000),
            null, true, 5000, 24000).source)
        assertEquals("enabled=false", calls.last())
        assertNull(controller.injectedFix)
    }
}
