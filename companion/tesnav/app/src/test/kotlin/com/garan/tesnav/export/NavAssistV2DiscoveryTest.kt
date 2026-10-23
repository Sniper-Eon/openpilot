package com.garan.tesnav.export

import java.net.InetAddress
import java.nio.charset.StandardCharsets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NavAssistV2DiscoveryTest {
    private val nonce = "00112233445566778899aabbccddeeff"
    private val app = AndroidKeystoreNavAssistIdentity.generatedForTest()
    private val device = AndroidKeystoreNavAssistIdentity.generatedForTest()

    @Test
    fun `signed request and device offer fit cross-client wire bounds`() {
        val request = NavAssistV2DiscoveryWire.request(nonce, app)
        assertTrue(request.size <= 403)
        assertTrue(request.toString(StandardCharsets.UTF_8).contains("\"appKeyId\":\"${app.keyId}\""))

        val offer = authenticatedOffer()
        assertTrue(offer.toByteArray(StandardCharsets.UTF_8).size <= 484)
        val parsed = NavAssistV2DiscoveryWire.authenticatedOffer(
            datagram("192.168.53.232", offer), nonce, app.keyId,
        )
        assertEquals(AuthenticatedDiscoveryOffer("192.168.53.232", device.keyId, device.publicKeyText), parsed)
    }

    @Test
    fun `first signed device is pinned and rediscovered without a manual token`() {
        val pairing = InMemoryPairingStore()
        val discovery = discoveryWith(pairing, datagram("192.168.53.232", authenticatedOffer()))

        assertEquals(NavAssistV2DiscoveryResult.Found("192.168.53.232", device.keyId), discovery.discover())
        assertEquals(PinnedNavAssistDevice(device.keyId, device.publicKeyText), pairing.pinnedDevice())
    }

    @Test
    fun `pinned device rejects a different valid C3 identity`() {
        val pairing = InMemoryPairingStore(PinnedNavAssistDevice(device.keyId, device.publicKeyText))
        val other = AndroidKeystoreNavAssistIdentity.generatedForTest()
        val discovery = discoveryWith(pairing, datagram("192.168.53.233", authenticatedOffer(other)))

        assertEquals(NavAssistV2DiscoveryResult.NotFound, discovery.discover())
    }

    @Test
    fun `two distinct signed devices fail closed after the whole discovery window`() {
        val other = AndroidKeystoreNavAssistIdentity.generatedForTest()
        val discovery = discoveryWith(
            InMemoryPairingStore(),
            datagram("192.168.53.232", authenticatedOffer()),
            datagram("192.168.53.233", authenticatedOffer(other)),
        )

        assertEquals(NavAssistV2DiscoveryResult.MultipleAuthenticatedHosts, discovery.discover())
    }

    @Test
    fun `tampered signature endpoint nonce and public sources are ignored`() {
        val invalid = listOf(
            authenticatedOffer().replace("\"path\":\"/v3/snapshot\"", "\"path\":\"/other\""),
            authenticatedOffer().replace(nonce, "ffeeddccbbaa99887766554433221100"),
            authenticatedOffer().replaceFirst("\"signature\":\"", "\"signature\":\"A"),
        )
        invalid.forEach { payload ->
            assertEquals(
                NavAssistV2DiscoveryResult.NotFound,
                discoveryWith(InMemoryPairingStore(), datagram("192.168.53.232", payload)).discover(),
            )
        }
        assertEquals(
            NavAssistV2DiscoveryResult.NotFound,
            discoveryWith(InMemoryPairingStore(), datagram("8.8.8.8", authenticatedOffer())).discover(),
        )
    }

    private fun discoveryWith(pairing: NavAssistDevicePinStore, vararg datagrams: NavAssistV2Datagram) =
        UdpNavAssistV2EndpointDiscovery(
            identity = app,
            pairingStore = pairing,
            transport = NavAssistV2DiscoveryTransport { datagrams.toList() },
            nonceFactory = { nonce },
        )

    private fun datagram(host: String, payload: String) = NavAssistV2Datagram(
        sourceAddress = InetAddress.getByName(host),
        payload = payload.toByteArray(StandardCharsets.UTF_8),
    )

    private fun authenticatedOffer(signer: NavAssistSigningIdentity = device): String {
        val material = NavAssistV2DiscoveryWire.offerSignatureMaterial(
            nonce, app.keyId, signer.keyId, signer.publicKeyText,
        )
        val signature = signer.sign(material.toByteArray(StandardCharsets.UTF_8))
        return "{\"messageType\":\"navassist_discovery_offer\",\"schemaVersion\":3," +
            "\"nonce\":\"$nonce\",\"appKeyId\":\"${app.keyId}\",\"deviceId\":\"${signer.keyId}\"," +
            "\"devicePublicKey\":\"${signer.publicKeyText}\",\"port\":7766,\"path\":\"/v3/snapshot\"," +
            "\"signature\":\"$signature\"}"
    }

    private class InMemoryPairingStore(initial: PinnedNavAssistDevice? = null) : NavAssistDevicePinStore {
        private var device = initial
        override fun pinnedDevice(): PinnedNavAssistDevice? = device
        override fun pin(device: PinnedNavAssistDevice): Boolean {
            if (this.device != null && this.device != device) return false
            this.device = device
            return true
        }
        override fun clear(): Boolean { device = null; return true }
    }
}
