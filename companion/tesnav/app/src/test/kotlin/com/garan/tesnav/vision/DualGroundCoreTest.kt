package com.garan.tesnav.vision

import org.junit.Assert.*
import org.junit.Test

class DualGroundCoreTest {
    // Synthetic linear ground map: X=0.1v, Y=0.01u-3.2. No camera accuracy claim.
    private val inverse=listOf(0.0,.1,0.0,.01,0.0,-3.2,0.0,0.0,1.0)
    private fun box(cx: Double=320.0, bottom: Double=200.0)=VehicleBox(cx-20,bottom-40,cx+20,bottom,.9)
    private fun associate(w: List<VehicleBox>,n: List<VehicleBox>,skew: Double=2.0)=
        DualGroundGeometry.associate(w,n,inverse,inverse,640,400,640,400,skew)
    @Test fun matchesOnlyMutuallyUniqueGroundCandidates() {
        assertEquals(1,associate(listOf(box()),listOf(box())).size)
        assertTrue(associate(listOf(box()),listOf(box(),box(cx=321.0))).isEmpty())
        assertTrue(associate(listOf(box(),box(cx=321.0)),listOf(box())).isEmpty())
    }
    @Test fun refusesMissingCalibrationAndDifferentRoadPosition() {
        assertNull(DualGroundGeometry.project(box(),null,640,400))
        assertTrue(associate(listOf(box()),listOf(box(cx=500.0))).isEmpty())
        assertTrue(associate(listOf(box()),listOf(box(bottom=300.0))).isEmpty())
        assertTrue(associate(listOf(box()),listOf(box()),21.0).isEmpty())
        assertTrue(associate(listOf(box()),listOf(box()),Double.NaN).isEmpty())
        assertNull(DualGroundGeometry.project(box(cx=10.0),inverse,640,400))
    }
    @Test fun fitsCaptureClockSpeedAndClearsStalls() {
        val tracker=DualGroundTracker();var rows=emptyList<DualGroundObservation>()
        repeat(8) {i ->
            val b=box(bottom=200.0-i*5);val m=associate(listOf(b),listOf(b))
            rows=tracker.update(m,listOf(b),1_000_000_000L+i*250_000_000L,10.0)
        }
        val result=rows.single();assertEquals(-2.0,result.relative_speed_mps!!,1e-6)
        assertEquals(8.0,result.absolute_speed_mps!!,1e-6)
        assertFalse(result.control_eligible);assertFalse(result.clearance_authorized)
        assertEquals("dual_ground_estimate",result.distance_source)
        assertTrue(tracker.update(emptyList(),emptyList(),3_000_000_000,10.0).isEmpty())
        val b=box();assertTrue(tracker.update(associate(listOf(b),listOf(b)),listOf(b),5_000_000_000,10.0).isEmpty())
    }
    @Test fun absentEgoDoesNotCreateAbsoluteSpeed() {
        val tracker=DualGroundTracker();var rows=emptyList<DualGroundObservation>()
        repeat(8) {i ->val b=box(bottom=200.0-i*5);rows=tracker.update(associate(listOf(b),listOf(b)),listOf(b),1_000_000_000L+i*250_000_000L,null)}
        assertNotNull(rows.single().relative_speed_mps);assertNull(rows.single().absolute_speed_mps)
        assertTrue(tracker.update(emptyList(),emptyList(),1_000_000_000L,10.0).isEmpty())
    }
}
