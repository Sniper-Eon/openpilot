package com.garan.tesnav.vision

import org.junit.Assert.*
import org.junit.Test

class PhoneVisionC3AddressTest {
    @Test fun `navigation discovery follows either wifi subnet without its navigation port`() {
        assertEquals("192.168.5.182", visionHostFromNavigationEndpoint("udp://192.168.5.182:4213"))
        assertEquals("10.138.196.108", visionHostFromNavigationEndpoint("udp://10.138.196.108:4213"))
    }
    @Test fun `resolved HTTP discovery and device hostname are accepted`() {
        assertEquals("comma-904f361e.local", visionHostFromNavigationEndpoint("http://comma-904f361e.local:7766"))
    }
    @Test fun `missing invalid or credential bearing endpoints preserve manual fallback`() {
        for (s in listOf(null, "", "192.168.5.182", "udp://", "file:///tmp/a", "http://user:password@host")) {
            assertNull(visionHostFromNavigationEndpoint(s))
        }
    }
}
