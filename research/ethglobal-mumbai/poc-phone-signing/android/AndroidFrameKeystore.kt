package com.enconomy.pop

import android.content.pm.PackageManager
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyInfo
import android.security.keystore.KeyProperties
import android.util.Log
import java.math.BigInteger
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.ProviderException
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec

/**
 * Standalone spike of the Android frame key. Not wired into the app (see ../patch/app.patch for that).
 *
 * Why a new alias: the existing pop-device-v1 key was generated with setDigests(DIGEST_SHA256) only.
 * Keystore enforces the digest list at sign time, so NONEwithECDSA on it fails with
 * "Incompatible digest". Digests are fixed at keygen, so the frame key is a second key.
 * DIGEST_SHA256 stays in the list so the same key could also sign server requests later.
 *
 * Keygen order: StrongBox (if the feature exists) -> TEE -> (emulator only) unattested software.
 * UNTESTED on hardware: whether StrongBox accepts DIGEST_NONE at keygen. If it doesn't, we expect a
 * ProviderException (StrongBoxUnavailableException extends it) and land on TEE.
 */
const val FRAME_KEY_ALIAS = "pop-frame-v1"
private const val TAG = "PopFrameKey"
private const val PROVIDER = "AndroidKeyStore"

class AndroidFrameKeystore(private val pm: PackageManager) {
    private val ks: KeyStore get() = KeyStore.getInstance(PROVIDER).apply { load(null) }

    /** What keygen actually did, for the debug screen. */
    var lastGenNote: String = ""
        private set

    fun load(): FrameKey? {
        val e = ks.getEntry(FRAME_KEY_ALIAS, null) as? KeyStore.PrivateKeyEntry ?: return null
        return AndroidFrameKey(e.privateKey, e.certificate.publicKey as ECPublicKey)
    }

    fun loadOrCreate(challenge: ByteArray? = null): FrameKey = load() ?: generate(challenge)

    fun delete() {
        val s = ks
        if (s.containsAlias(FRAME_KEY_ALIAS)) s.deleteEntry(FRAME_KEY_ALIAS)
    }

    /** Attestation chain of the frame key (leaf..root DER), null if none. */
    fun chain(): List<ByteArray>? = ks.getCertificateChain(FRAME_KEY_ALIAS)?.map { it.encoded }

    fun generate(challenge: ByteArray?): FrameKey {
        delete()
        val notes = mutableListOf<String>()
        val sbFeature = Build.VERSION.SDK_INT >= 28 && pm.hasSystemFeature(PackageManager.FEATURE_STRONGBOX_KEYSTORE)
        var done = false
        if (sbFeature) {
            try {
                gen(challenge, strongBox = true); done = true; notes += "strongbox ok"
            } catch (e: ProviderException) {
                notes += "strongbox failed: ${e.javaClass.simpleName}: ${e.message}"
                Log.w(TAG, "StrongBox keygen with DIGEST_NONE failed, trying TEE", e)
            }
        } else notes += "no strongbox feature"
        if (!done) {
            try {
                gen(challenge, strongBox = false); notes += "tee ok"
            } catch (e: Exception) {
                if (!isEmulator()) throw IllegalStateException("frame keygen failed: $e", e)
                notes += "attested keygen failed on emulator: $e"
                gen(null, strongBox = false); notes += "plain key"
            }
        }
        lastGenNote = notes.joinToString("; ")
        Log.i(TAG, lastGenNote)
        return load() ?: error("frame key missing after generate")
    }

    private fun gen(challenge: ByteArray?, strongBox: Boolean) {
        val b = KeyGenParameterSpec.Builder(FRAME_KEY_ALIAS, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256)
        if (challenge != null) b.setAttestationChallenge(challenge)
        if (strongBox && Build.VERSION.SDK_INT >= 28) b.setIsStrongBoxBacked(true)
        KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, PROVIDER).apply {
            initialize(b.build())
            generateKeyPair()
        }
    }
}

private class AndroidFrameKey(private val priv: PrivateKey, pub: ECPublicKey) : FrameKey {
    override val pubkey: ByteArray = byteArrayOf(4) + fixed32(pub.w.affineX) + fixed32(pub.w.affineY)

    override val securityLevel: String by lazy {
        try {
            val info = KeyFactory.getInstance(priv.algorithm, PROVIDER).getKeySpec(priv, KeyInfo::class.java)
            if (Build.VERSION.SDK_INT >= 31) when (info.securityLevel) {
                KeyProperties.SECURITY_LEVEL_STRONGBOX -> "strongbox"
                KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT -> "tee"
                KeyProperties.SECURITY_LEVEL_SOFTWARE -> "software"
                else -> "unknown"
            } else {
                @Suppress("DEPRECATION")
                if (info.isInsideSecureHardware) "hardware" else "software"
            }
        } catch (e: Exception) {
            "unknown"
        }
    }

    /**
     * NONEwithECDSA: Keystore takes the input as the hash value e. For a P-256 key and a 32-byte input
     * that is exactly ECDSA over the digest (inputs longer than 32 bytes get truncated, so we refuse them).
     */
    override fun signDigest(digest32: ByteArray): ByteArray {
        FrameSig.requireDigest(digest32)
        val der = Signature.getInstance("NONEwithECDSA").run {
            initSign(priv)
            update(digest32)
            sign()
        }
        return FrameSig.normalizeLowS(derToRawRs(der))
    }
}

private fun isEmulator(): Boolean =
    Build.FINGERPRINT.startsWith("generic") || Build.FINGERPRINT.contains("emulator") ||
        Build.HARDWARE in setOf("goldfish", "ranchu") || Build.PRODUCT.contains("sdk")

private fun fixed32(v: BigInteger): ByteArray {
    val b = v.toByteArray()
    return when {
        b.size == 32 -> b
        b.size > 32 -> b.copyOfRange(b.size - 32, b.size)
        else -> ByteArray(32 - b.size) + b
    }
}
