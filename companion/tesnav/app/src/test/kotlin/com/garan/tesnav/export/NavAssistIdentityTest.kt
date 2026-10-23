package com.garan.tesnav.export

import java.nio.charset.StandardCharsets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NavAssistIdentityTest {
    @Test
    fun `P256 identity signs and verifies canonical material`() {
        val identity = AndroidKeystoreNavAssistIdentity.generatedForTest()
        val material = "navassist-test".toByteArray(StandardCharsets.UTF_8)
        val signature = identity.sign(material)

        assertEquals(32, identity.keyId.length)
        assertEquals(NavAssistEcdsa.PUBLIC_KEY_TEXT_LENGTH, identity.publicKeyText.length)
        assertEquals(identity.keyId, NavAssistEcdsa.publicKeyId(identity.publicKeyText))
        assertTrue(NavAssistEcdsa.verify(identity.publicKeyText, material, signature))
        assertFalse(NavAssistEcdsa.verify(identity.publicKeyText, material + byteArrayOf(0), signature))
    }

    @Test
    fun `snapshot signature binds device app path length and raw body`() {
        val body = "{\"schemaVersion\":3}".toByteArray(StandardCharsets.UTF_8)
        val material = NavAssistV3Auth.snapshotSignatureMaterial("d".repeat(32), "a".repeat(32), "/v3/snapshot", body)

        assertTrue(material.toString(StandardCharsets.UTF_8).startsWith(
            "navassist_snapshot\n3\nPOST\n/v3/snapshot\n${"d".repeat(32)}\n${"a".repeat(32)}\n${body.size}\n",
        ))
        assertTrue(material.copyOfRange(material.size - body.size, material.size).contentEquals(body))
    }
}
