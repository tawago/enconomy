package com.enconomy.pop

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Log
import java.security.GeneralSecurityException
import java.security.KeyFactory
import java.security.KeyStore
import java.security.SecureRandom
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private const val TAG = "PopSecrets"
private const val PROVIDER = "AndroidKeyStore"
private const val WRAP_ALIAS = "pop-secrets-v1"

actual fun createSecretStore(): SecretStore = AndroidSecretStore(PopApplication.instance)

/**
 * AES-256-GCM key in AndroidKeyStore (non-exportable, TEE/StrongBox), blobs iv(12) || ct+tag in private
 * prefs "pop_secret", AAD = name. A blob the key cannot open (key gone, restored backup) reads as absent.
 */
class AndroidSecretStore(ctx: Context) : SecretStore {
    private val sp = ctx.getSharedPreferences("pop_secret", Context.MODE_PRIVATE)

    private fun wrapKey(create: Boolean): SecretKey? {
        val ks = KeyStore.getInstance(PROVIDER).apply { load(null) }
        (ks.getKey(WRAP_ALIAS, null) as? SecretKey)?.let { return it }
        if (!create) return null
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, PROVIDER).run {
            init(
                KeyGenParameterSpec.Builder(WRAP_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
            generateKey()
        }
    }

    override fun get(name: String): ByteArray? {
        val blob = sp.getString(name, null)?.let { runCatching { it.fromB64() }.getOrNull() } ?: return null
        if (blob.size < 12 + 16) return null
        val key = wrapKey(create = false) ?: run { Log.w(TAG, "$name: wrap key missing"); return null }
        return try {
            Cipher.getInstance("AES/GCM/NoPadding").run {
                init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, blob, 0, 12))
                updateAAD(name.encodeToByteArray())
                doFinal(blob, 12, blob.size - 12)
            }
        } catch (e: GeneralSecurityException) {
            Log.w(TAG, "$name: cannot decrypt: $e"); null
        }
    }

    override fun put(name: String, value: ByteArray) {
        val key = wrapKey(create = true)!!
        val blob = Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.ENCRYPT_MODE, key)
            updateAAD(name.encodeToByteArray())
            val ct = doFinal(value)
            iv.also { require(it.size == 12) } + ct
        }
        check(sp.edit().putString(name, blob.toB64()).commit()) { "secret $name not written" }
    }

    override fun delete(name: String) {
        sp.edit().remove(name).commit()
    }
}

actual fun secureRandomBytes(n: Int): ByteArray = ByteArray(n).also { SecureRandom().nextBytes(it) }

/** SubjectPublicKeyInfo header for an uncompressed P-256 point (id-ecPublicKey, prime256v1). */
private val SPKI_P256 = "3059301306072a8648ce3d020106082a8648ce3d030107034200".hexToBytes()

actual fun ecdsaP256Verify(pub65: ByteArray, message: ByteArray, sig: ByteArray): Boolean {
    if (pub65.size != 65 || pub65[0] != 4.toByte() || sig.size != 64) return false
    return try {
        val pk = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(SPKI_P256 + pub65))
        Signature.getInstance("SHA256withECDSA").run {
            initVerify(pk)
            update(message)
            verify(rawRsToDer(sig))
        }
    } catch (e: GeneralSecurityException) {
        false
    } catch (e: IllegalArgumentException) {
        false
    }
}
