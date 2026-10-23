package com.garan.tesnav.vision

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.roundToLong

class SideVehicleCoreTest {
    private val box = VehicleBox(100.0, 200.0, 140.0, 300.0, .9)
    @Test fun speedUsesCaptureTimeAndNeverInventsMissingGeometry() {
        val tracker = SideVehicleTracker()
        var result: SideObservation? = null
        repeat(6) { i -> result = tracker.update(listOf(SideDetection(box, "left", 20.0 - i * .5)), 1_000_000_000L + i * 250_000_000L, 15.0)["left"] }
        assertNotNull(result)
        assertEquals(-2.0, result!!.relative_speed_mps!!, 1e-8)
        assertEquals(13.0, result!!.absolute_speed_mps!!, 1e-8)
        val uncalibrated = tracker.update(listOf(SideDetection(box, "left", null)), 2_500_000_000, 15.0)["left"]!!
        assertNull(uncalibrated.distance_m)
        assertNull(uncalibrated.relative_speed_mps)
    }
    @Test fun missedFramesDoNotReturnOldTracksOrRefreshTheirTime() {
        val tracker = SideVehicleTracker()
        repeat(5) { tracker.update(listOf(SideDetection(box, "left", 20.0)), 1_000_000_000L + it * 250_000_000L, 15.0) }
        assertNull(tracker.update(emptyList(), 2_250_000_000, 15.0)["left"])
        assertNull(tracker.update(listOf(SideDetection(box, "left", 20.0)), 5_000_000_000, 15.0)["left"])
    }
    @Test fun duplicateFramesCannotCreateTrackHits() {
        val tracker = SideVehicleTracker()
        repeat(20) { assertNull(tracker.update(listOf(SideDetection(box, "left", 20.0)), 1_000_000_000L, 15.0)["left"]) }
    }
    @Test fun discontinuousDistancesDoNotBecomeSpeeds() {
        val tracker = SideVehicleTracker()
        repeat(5) { tracker.update(listOf(SideDetection(box, "left", 20.0)), 1_000_000_000L + it * 250_000_000L, 15.0) }
        assertNull(tracker.update(listOf(SideDetection(box, "left", 40.0)), 2_250_000_000, 15.0)["left"])
    }
    @Test fun projectionRejectsMissingCalibrationAndClippedObjects() {
        assertNull(SideVehicleGeometry.distance(box, null, 960, 601))
        val inverse = listOf(0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        assertEquals(20.0, SideVehicleGeometry.distance(box, inverse, 960, 601)!!, .001)
        assertNull(SideVehicleGeometry.distance(box.copy(y2 = 600.0), inverse, 960, 601))
    }
    @Test fun modelOutputDecodesAndSuppressesDuplicateBoxes() {
        val output = arrayOf(floatArrayOf(160f, 160f), floatArrayOf(160f, 160f), floatArrayOf(40f, 40f), floatArrayOf(40f, 40f), floatArrayOf(.9f, .8f))
        assertEquals(1, SideVehicleGeometry.decode(output, 960, 600).size)
    }

    @Test fun sceneSizedFalseBoxesAreRejectedWithoutRemovingSmallerVehicles() {
        val output = arrayOf(floatArrayOf(160f, 160f), floatArrayOf(160f, 160f),
            floatArrayOf(320f, 40f), floatArrayOf(320f, 40f), floatArrayOf(.99f, .9f))
        val boxes = SideVehicleGeometry.decode(output, 960, 600)
        assertEquals(1, boxes.size)
        assertEquals(120.0, boxes.single().x2 - boxes.single().x1, 1e-8)
        // A large partial side view is not a whole-scene box.
        val partial = arrayOf(floatArrayOf(160f), floatArrayOf(160f),
            floatArrayOf(200f), floatArrayOf(180f), floatArrayOf(.9f))
        assertEquals(1, SideVehicleGeometry.decode(partial, 960, 600).size)
    }

    @Test fun absoluteSpeedCompensatesAccelerationOverTheSameCaptureWindow() {
        for ((acceleration, initial) in listOf(0.0 to 10.0, 2.0 to 10.0, -2.0 to 15.0)) {
            val tracker = SideVehicleTracker()
            var result: SideObservation? = null
            repeat(11) { i ->
                val t = i * .25
                val distance = 4.0 + (15.0 - initial) * t - .5 * acceleration * t * t
                result = tracker.update(listOf(SideDetection(box, "left", distance)),
                    1_000_000_000L + i * 250_000_000L, initial + acceleration * t)["left"]
            }
            assertEquals("a=$acceleration", 15.0, result!!.absolute_speed_mps!!, 1e-8)
        }
    }

    @Test fun changingEgoSpeedUsesTrapezoidalIntegrationAtIrregularCaptureTimes() {
        val tracker = SideVehicleTracker()
        val times = listOf(0.0, .2, .55, .8, 1.1, 1.35, 1.7, 2.0)
        val egos = listOf(10.0, 11.0, 10.5, 12.0, 11.0, 10.0, 11.0, 12.0)
        var travelled = 0.0
        var result: SideObservation? = null
        times.indices.forEach { i ->
            if (i > 0) travelled += (egos[i - 1] + egos[i]) * .5 * (times[i] - times[i - 1])
            result = tracker.update(listOf(SideDetection(box, "left", 5.0 + 15.0 * times[i] - travelled)),
                1_000_000_000L + (times[i] * 1e9).roundToLong(), egos[i])["left"]
        }
        assertEquals(15.0, result!!.absolute_speed_mps!!, 1e-8)
    }

    @Test fun unavailableEgoSpeedRequiresANewContinuousWindowForAbsoluteSpeed() {
        for (missing in listOf<Double?>(null, Double.NaN, Double.POSITIVE_INFINITY)) {
            val tracker = SideVehicleTracker()
            fun frame(i: Int, ego: Double?) = tracker.update(listOf(SideDetection(box, "left", 10.0)),
                1_000_000_000L + i * 250_000_000L, ego)["left"]
            repeat(6) { frame(it, 10.0) }
            val unavailable = frame(6, missing)!!
            assertNotNull(unavailable.relative_speed_mps)
            assertNull(unavailable.absolute_speed_mps)
            for (i in 7..10) assertNull(frame(i, 10.0)!!.absolute_speed_mps)
            assertEquals(10.0, frame(11, 10.0)!!.absolute_speed_mps!!, 1e-8)
        }
    }

    @Test fun duplicateCaptureCannotChangeIntegratedMotion() {
        val tracker = SideVehicleTracker()
        var result: SideObservation? = null
        repeat(8) { i ->
            val t = 1_000_000_000L + i * 250_000_000L
            result = tracker.update(listOf(SideDetection(box, "left", 10.0)), t, 10.0)["left"]
            assertNull(tracker.update(listOf(SideDetection(box, "left", 10.0)), t, 1000.0)["left"])
        }
        assertEquals(10.0, result!!.absolute_speed_mps!!, 1e-8)
    }
}
