package com.garan.tesnav.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class StructuredTrafficLightTest {
    @Test fun `reads vendor traffic light countdown without depending on object layout`() {
        assertEquals(37, structuredTrafficLightCountdown("""{"trafficLightCountDown":37}"""))
        assertEquals(18, structuredTrafficLightCountdown("""{"guide":{"trafficLight":{"countDownSeconds":"18"}}}"""))
    }

    @Test fun `does not treat unrelated countdowns as traffic lights`() {
        assertNull(structuredTrafficLightCountdown("""{"camera":{"countdown":12}}"""))
        assertNull(structuredTrafficLightCountdown("""{"trafficLightCountDown":-1}"""))
        assertNull(structuredTrafficLightCountdown("""{"trafficLight":{"countdown":3601}}"""))
        assertNull(structuredTrafficLightCountdown("not-json"))
    }
}
