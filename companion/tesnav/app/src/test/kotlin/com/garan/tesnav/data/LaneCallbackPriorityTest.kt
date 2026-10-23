package com.garan.tesnav.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LaneCallbackPriorityTest {
    @Test fun pairedLegacyCallbackCannotOverwriteModernResult() {
        assertTrue(modernLaneCallbackOwnsResult("data", 1_000L, 42L, 42L, 1_022L))
        assertTrue(modernLaneCallbackOwnsResult("empty", 1_000L, 42L, 42L, 1_022L))
    }

    @Test fun oldOrDifferentRouteModernCallbackAllowsLegacyFallback() {
        assertFalse(modernLaneCallbackOwnsResult("data", 1_000L, 42L, 42L, 2_001L))
        assertFalse(modernLaneCallbackOwnsResult("data", 1_000L, 42L, 43L, 1_022L))
        assertFalse(modernLaneCallbackOwnsResult("hidden", 1_000L, 42L, 42L, 1_022L))
        assertFalse(modernLaneCallbackOwnsResult("data", null, 42L, 42L, 1_022L))
    }
}
