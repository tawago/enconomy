package com.enconomy.pop

import android.content.Context
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

private const val TAG = "PopKeystore"
private const val PROVIDER = "AndroidKeyStore"

/**
 * Contract §2.1: EC P-256, SIGN, SHA-256, attestation challenge = enroll nonce.
 * StrongBox first (API 28+ with the feature); on failure, TEE.
 * Unattested fallback (plain key, no chain) only on emulators; a real phone surfaces the keygen error.
 */
class AndroidDeviceKeystore(private val ctx: Context) : DeviceKeystore {
    private val ks: KeyStore get() = KeyStore.getInstance(PROVIDER).apply { load(null) }

    override fun load(): DeviceKey? {
        val entry = ks.getEntry(KEY_ALIAS, null) as? KeyStore.PrivateKeyEntry ?: return null
        return AndroidDeviceKey(entry.privateKey, entry.certificate.publicKey as ECPublicKey)
    }

    override fun delete() {
        val s = ks
        if (s.containsAlias(KEY_ALIAS)) s.deleteEntry(KEY_ALIAS)
        Prefs.set("key.strongbox", null)
    }

    override fun generate(challenge: ByteArray): GeneratedKey {
        delete()
        val sbFeature = Build.VERSION.SDK_INT >= 28 &&
            ctx.packageManager.hasSystemFeature(PackageManager.FEATURE_STRONGBOX_KEYSTORE)
        var attested = true
        var strongBox = false
        if (sbFeature) {
            try {
                gen(challenge, strongBox = true); strongBox = true
            } catch (e: ProviderException) { // StrongBoxUnavailableException extends it
                Log.w(TAG, "StrongBox failed, falling back to TEE: $e")
            }
        }
        if (!strongBox) {
            try {
                gen(challenge, strongBox = false)
            } catch (e: Exception) {
                if (!isEmulator()) throw IllegalStateException("attested keygen failed: $e", e)
                Log.w(TAG, "attested keygen failed on emulator, plain key: $e")
                gen(null, strongBox = false); attested = false
            }
        }
        Prefs.set("key.strongbox", if (strongBox) "1" else "0")
        val key = load() ?: error("key missing after generate")
        val chain = if (attested) ks.getCertificateChain(KEY_ALIAS)?.map { it.encoded } else null
        Log.i(TAG, "generated ${key.deviceId} level=${key.securityLevel} chain=${chain?.size}")
        return GeneratedKey(key, chain)
    }

    private fun gen(challenge: ByteArray?, strongBox: Boolean) {
        val b = KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
        if (challenge != null) b.setAttestationChallenge(challenge)
        if (strongBox && Build.VERSION.SDK_INT >= 28) b.setIsStrongBoxBacked(true)
        KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, PROVIDER).apply {
            initialize(b.build())
            generateKeyPair()
        }
    }
}

private fun isEmulator(): Boolean =
    Build.FINGERPRINT.startsWith("generic") || Build.FINGERPRINT.contains("emulator") ||
        Build.HARDWARE in setOf("goldfish", "ranchu") || Build.PRODUCT.contains("sdk")

private class AndroidDeviceKey(private val priv: PrivateKey, pub: ECPublicKey) : DeviceKey {
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
                when {
                    !info.isInsideSecureHardware -> "software"
                    Prefs.get("key.strongbox") == "1" -> "strongbox"
                    else -> "tee"
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "KeyInfo failed: $e"); "unknown"
        }
    }

    override fun sign(message: ByteArray): ByteArray {
        val der = Signature.getInstance("SHA256withECDSA").run {
            initSign(priv)
            update(message)
            sign()
        }
        return derToRawRs(der)
    }
}

private fun fixed32(v: BigInteger): ByteArray {
    val b = v.toByteArray()
    return when {
        b.size == 32 -> b
        b.size > 32 -> b.copyOfRange(b.size - 32, b.size)
        else -> ByteArray(32 - b.size) + b
    }
}
