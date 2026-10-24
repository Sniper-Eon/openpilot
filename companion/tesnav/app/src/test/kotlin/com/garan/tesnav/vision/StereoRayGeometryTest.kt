package com.garan.tesnav.vision

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.abs

class StereoRayGeometryTest {
    private val r=listOf(1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0)
    @Test fun recoversKnownPointWithDifferentFocals() {
        val t=listOf(-.3,0.0,0.0)
        // Camera pixels (338,206) / (320,212), focal lengths 600/1200.
        val p=StereoRayGeometry.point((338.0-320)/600,(206.0-200)/600,0.0,(212.0-200)/1200,r,t)!!
        assertArrayEquals(doubleArrayOf(.3,.1,10.0),p,1e-6)
        val view=listOf(0.0,1.0,0.0,0.0,0.0,0.0,1.0,1.5,1.0,0.0,0.0,0.0)
        val road=StereoRayGeometry.roadPoint(p,r,t,view)!!
        assertEquals(10.0,road.forward,1e-6);assertEquals(0.0,road.lateral,1e-6)
        assertNull(StereoRayGeometry.roadPoint(p,r,t,null))
    }
    @Test fun refusesParallelBehindAndEpipolarMismatch() {
        val t=listOf(-.06,0.0,0.0)
        assertNull(StereoRayGeometry.point(0.0,0.0,0.0,0.0,r,t))
        assertNull(StereoRayGeometry.point(0.0,0.0,.01,0.0,r,t))
        assertNull(StereoRayGeometry.point(0.0,0.0,-.03,.1,r,t))
    }
    @Test fun worksWithRotatedCameraExtrinsics() {
        val angle=.03;val c=kotlin.math.cos(angle);val s=kotlin.math.sin(angle)
        val rotation=listOf(c,0.0,s,0.0,1.0,0.0,-s,0.0,c);val translation=listOf(-.3,0.0,0.0)
        val known=doubleArrayOf(.3,.1,10.0);val n=StereoRayGeometry.mul(rotation,known)
        for(i in 0..2)n[i]+=translation[i]
        val recovered=StereoRayGeometry.point(known[0]/known[2],known[1]/known[2],n[0]/n[2],n[1]/n[2],rotation,translation)!!
        assertArrayEquals(known,recovered,1e-6)
    }
    @Test fun sensitivityAndTimingCanRejectEvenPerfectNominalDepth() {
        val p=doubleArrayOf(0.0,0.0,4.0)
        val shifts=List(8) { p.copyOf() }
        assertTrue(StereoRayGeometry.reliable(p,shifts,.06,0))
        assertFalse(StereoRayGeometry.reliable(p,shifts,.06,1_000_000))
        assertFalse(StereoRayGeometry.reliable(p,shifts,.06,6_000_000))
        assertFalse(StereoRayGeometry.reliable(p,List(8) { doubleArrayOf(0.0,0.0,8.0) },.06,0))
        assertFalse(StereoRayGeometry.reliable(p,List(8) { null },.06,0))
    }
}
