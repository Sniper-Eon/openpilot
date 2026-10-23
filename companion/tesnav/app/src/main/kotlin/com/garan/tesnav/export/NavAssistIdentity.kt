package com.garan.tesnav.export

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.nio.charset.StandardCharsets
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.PublicKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.security.spec.X509EncodedKeySpec
import okio.ByteString.Companion.decodeBase64
import okio.ByteString.Companion.toByteString

internal interface NavAssistSigningIdentity {
    val keyId: String
    val publicKeyText: String
    fun sign(material: ByteArray): String
}

internal class AndroidKeystoreNavAssistIdentity private constructor(
    private val privateKey: PrivateKey,
    publicKey: PublicKey,
) : NavAssistSigningIdentity {
    override val publicKeyText: String = NavAssistEcdsa.encodePublicKey(publicKey)
    override val keyId: String = NavAssistEcdsa.publicKeyId(publicKeyText)

    override fun sign(material: ByteArray): String = NavAssistEcdsa.sign(privateKey, material)

    companion object {
        private const val KEYSTORE = "AndroidKeyStore"
        private const val ALIAS = "tesnav_navassist_v3_signing"

        fun loadOrCreate(@Suppress("UNUSED_PARAMETER") context: Context): AndroidKeystoreNavAssistIdentity {
            val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
            if (!keyStore.containsAlias(ALIAS)) {
                val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, KEYSTORE)
                generator.initialize(
                    KeyGenParameterSpec.Builder(
                        ALIAS,
                        KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
                    )
                        .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                        .setDigests(KeyProperties.DIGEST_SHA256)
                        .setUserAuthenticationRequired(false)
                        .build(),
                )
                generator.generateKeyPair()
            }
            val privateKey = keyStore.getKey(ALIAS, null) as? PrivateKey
                ?: error("NavAssist Android Keystore private key is unavailable")
            val publicKey = keyStore.getCertificate(ALIAS)?.publicKey
                ?: error("NavAssist Android Keystore public key is unavailable")
            return AndroidKeystoreNavAssistIdentity(privateKey, publicKey)
        }

        internal fun generatedForTest(): NavAssistSigningIdentity {
            val generator = KeyPairGenerator.getInstance("EC")
            generator.initialize(ECGenParameterSpec("secp256r1"))
            val pair: KeyPair = generator.generateKeyPair()
            return AndroidKeystoreNavAssistIdentity(pair.private, pair.public)
        }
    }
}

internal object NavAssistEcdsa {
    const val PUBLIC_KEY_DER_BYTES = 91
    const val PUBLIC_KEY_TEXT_LENGTH = 122
    const val MAX_SIGNATURE_DER_BYTES = 72
    private val KEY_ID_REGEX = Regex("^[0-9a-f]{32}$")
    private val PUBLIC_KEY_REGEX = Regex("^[A-Za-z0-9_-]{122}$")
    private val SIGNATURE_REGEX = Regex("^[A-Za-z0-9_-]{1,96}$")

    fun encodePublicKey(publicKey: PublicKey): String {
        val encoded = publicKey.encoded
        require(encoded.size == PUBLIC_KEY_DER_BYTES) { "unexpected P-256 public-key encoding" }
        val text = base64UrlEncode(encoded)
        require(PUBLIC_KEY_REGEX.matches(text)) { "invalid P-256 public key" }
        return text
    }

    fun publicKeyId(publicKeyText: String): String {
        val encoded = decodePublicKeyBytes(publicKeyText)
        return MessageDigest.getInstance("SHA-256").digest(encoded).take(16)
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

    fun validKeyId(value: String): Boolean = KEY_ID_REGEX.matches(value)

    fun decodePublicKey(publicKeyText: String): PublicKey {
        val encoded = decodePublicKeyBytes(publicKeyText)
        val publicKey = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(encoded))
        require(publicKey.encoded.contentEquals(encoded)) { "public-key encoding must be canonical" }
        return publicKey
    }

    fun sign(privateKey: PrivateKey, material: ByteArray): String {
        val signature = Signature.getInstance("SHA256withECDSA").run {
            initSign(privateKey)
            update(material)
            sign()
        }
        require(signature.size in 1..MAX_SIGNATURE_DER_BYTES) { "P-256 signature exceeded DER bound" }
        return base64UrlEncode(signature)
    }

    fun verify(publicKeyText: String, material: ByteArray, signatureText: String): Boolean = runCatching {
        if (!SIGNATURE_REGEX.matches(signatureText)) return false
        val signature = base64UrlDecode(signatureText)
        if (signature.size !in 1..MAX_SIGNATURE_DER_BYTES) return false
        Signature.getInstance("SHA256withECDSA").run {
            initVerify(decodePublicKey(publicKeyText))
            update(material)
            verify(signature)
        }
    }.getOrDefault(false)

    private fun decodePublicKeyBytes(publicKeyText: String): ByteArray {
        require(PUBLIC_KEY_REGEX.matches(publicKeyText)) { "invalid P-256 public key" }
        return base64UrlDecode(publicKeyText).also {
            require(it.size == PUBLIC_KEY_DER_BYTES) { "invalid P-256 public key size" }
        }
    }

    private fun base64UrlEncode(value: ByteArray): String =
        value.toByteString().base64Url().trimEnd('=')

    private fun base64UrlDecode(value: String): ByteArray =
        value.decodeBase64()?.toByteArray() ?: throw IllegalArgumentException("invalid base64url")
}

internal data class PinnedNavAssistDevice(
    val deviceId: String,
    val publicKey: String,
)

internal interface NavAssistDevicePinStore {
    fun pinnedDevice(): PinnedNavAssistDevice?
    fun pin(device: PinnedNavAssistDevice): Boolean
    fun clear(): Boolean
}

internal class NavAssistPairingStore(context: Context) : NavAssistDevicePinStore {
    private val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    @Synchronized
    override fun pinnedDevice(): PinnedNavAssistDevice? {
        val deviceId = preferences.getString(DEVICE_ID, null) ?: return null
        val publicKey = preferences.getString(PUBLIC_KEY, null) ?: return null
        return runCatching {
            require(NavAssistEcdsa.validKeyId(deviceId))
            require(NavAssistEcdsa.publicKeyId(publicKey) == deviceId)
            PinnedNavAssistDevice(deviceId, publicKey)
        }.getOrNull()
    }

    @Synchronized
    override fun pin(device: PinnedNavAssistDevice): Boolean {
        if (!NavAssistEcdsa.validKeyId(device.deviceId) ||
            runCatching { NavAssistEcdsa.publicKeyId(device.publicKey) }.getOrNull() != device.deviceId
        ) return false
        val current = pinnedDevice()
        if (current != null && current != device) return false
        return preferences.edit()
            .putString(DEVICE_ID, device.deviceId)
            .putString(PUBLIC_KEY, device.publicKey)
            .commit()
    }

    @Synchronized
    override fun clear(): Boolean = preferences.edit().clear().commit()

    private companion object {
        const val PREFERENCES = "navassist_pairing_v3"
        const val DEVICE_ID = "device_id"
        const val PUBLIC_KEY = "device_public_key"
    }
}

internal object NavAssistV3Auth {
    const val KEY_ID_HEADER = "X-NavAssist-Key-Id"
    const val SIGNATURE_HEADER = "X-NavAssist-Signature"

    fun snapshotSignatureMaterial(deviceId: String, appKeyId: String, path: String, body: ByteArray): ByteArray {
        val prefix = "navassist_snapshot\n3\nPOST\n$path\n$deviceId\n$appKeyId\n${body.size}\n"
            .toByteArray(StandardCharsets.US_ASCII)
        return prefix + body
    }
}
