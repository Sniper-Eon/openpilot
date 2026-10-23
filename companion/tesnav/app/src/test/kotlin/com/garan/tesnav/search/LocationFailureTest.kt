package com.garan.tesnav.search

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LocationFailureTest {
    @Test
    fun `map location extras error takes priority over subtype fallback`() {
        assertEquals(
            LocationFailure(12, "网络定位失败"),
            selectLocationFailure(
                extrasErrorCode = 12,
                extrasErrorInfo = "网络定位失败",
                subtypeErrorCode = 0,
                subtypeErrorInfo = null,
            ),
        )
        assertNull(selectLocationFailure(0, null, 0, null))
    }
}
