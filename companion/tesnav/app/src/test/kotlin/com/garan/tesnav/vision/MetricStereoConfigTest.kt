package com.garan.tesnav.vision

import org.junit.Assert.*
import org.junit.Test

class MetricStereoConfigTest {
    private fun config(): MetricStereoConfig {
        val cam=StereoCameraConfig(listOf(640,400),listOf(listOf(600.0,0.0,320.0),listOf(0.0,600.0,200.0),listOf(0.0,0.0,1.0)),List(5){0.0},"radtan")
        return MetricStereoConfig(1,true,"metres","synthetic",listOf("wide-test","narrow-test"),20,5,.1,.2,cam,cam,
            listOf(listOf(1.0,0.0,0.0),listOf(0.0,1.0,0.0),listOf(0.0,0.0,1.0)),listOf(-.06,0.0,0.0))
    }
    @Test fun rejectsMissingQualityUnitsBaselineAndReflection() {
        val valid=config();PhoneStereoMatcher.validate(valid)
        val invalid=listOf(valid.copy(stereo_rms_px=null),valid.copy(heldout_rms_px=null),valid.copy(validated=false),
            valid.copy(units="millimetres"),valid.copy(t_narrow_from_wide_m=listOf(0.0,0.0,0.0)),
            valid.copy(R_narrow_from_wide=listOf(listOf(-1.0,0.0,0.0),listOf(0.0,1.0,0.0),listOf(0.0,0.0,1.0))))
        for(candidate in invalid) {
            try {PhoneStereoMatcher.validate(candidate);fail("invalid calibration accepted")}
            catch(expected: IllegalArgumentException) {}
        }
    }
}
