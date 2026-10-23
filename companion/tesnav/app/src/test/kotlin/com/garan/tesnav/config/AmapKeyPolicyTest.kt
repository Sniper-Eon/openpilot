package com.garan.tesnav.config

import org.junit.Assert.*
import org.junit.Test

class AmapKeyPolicyTest {
    @Test fun missingAndPlaceholderKeysRequireSetup() {
        for (value in listOf(null, "", "   ", "\${AMAP_API_KEY}", "YOUR_API_KEY", "https://example.com")) {
            assertNull(AmapKeyPolicy.resolve(null, value))
        }
    }

    @Test fun savedKeyOverridesBundledKeyAndWhitespaceIsTrimmed() {
        val bundled = "a".repeat(32)
        val saved = "b".repeat(32)
        assertEquals(saved, AmapKeyPolicy.resolve(" $saved\n", bundled))
        assertEquals(bundled, AmapKeyPolicy.resolve(null, bundled))
        assertNull(AmapKeyPolicy.resolve("invalid", bundled))
    }
}
