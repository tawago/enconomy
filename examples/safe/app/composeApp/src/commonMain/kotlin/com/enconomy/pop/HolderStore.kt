package com.enconomy.pop

import com.enconomy.pop.zk.Fe
import com.enconomy.pop.zk.Holder
import com.enconomy.pop.zk.Sbcred3
import com.enconomy.pop.zk.StoredCredential

/**
 * Small secrets at rest in hardware-protected storage.
 * Android: AES-256-GCM under an AndroidKeyStore key, ciphertext in private prefs.
 * iOS: keychain generic password, AfterFirstUnlockThisDeviceOnly.
 */
interface SecretStore {
    fun get(name: String): ByteArray?
    /** Durable when it returns. */
    fun put(name: String, value: ByteArray)
    fun delete(name: String)
}

expect fun createSecretStore(): SecretStore

/** CSPRNG. */
expect fun secureRandomBytes(n: Int): ByteArray

/** ES256 verify: SHA-256 over [message], [sig] raw r||s, [pub65] 04||X||Y. False on any malformed input. */
expect fun ecdsaP256Verify(pub65: ByteArray, message: ByteArray, sig: ByteArray): Boolean

/** raw r||s (32 + 32) -> DER ECDSA-Sig-Value. */
fun rawRsToDer(raw: ByteArray): ByteArray {
    require(raw.size == 64) { "raw sig must be 64 bytes" }
    fun int(v: ByteArray): ByteArray {
        var s = 0
        while (s < v.size - 1 && v[s] == 0.toByte()) s++
        val t = v.copyOfRange(s, v.size)
        val b = if (t[0] < 0) byteArrayOf(0) + t else t
        return byteArrayOf(0x02, b.size.toByte()) + b
    }
    val body = int(raw.copyOf(32)) + int(raw.copyOfRange(32, 64))
    return byteArrayOf(0x30, body.size.toByte()) + body
}

interface KeyValue {
    fun get(key: String): String?
    fun set(key: String, value: String?)
}

object PrefsKeyValue : KeyValue {
    override fun get(key: String) = Prefs.get(key)
    override fun set(key: String, value: String?) = Prefs.set(key, value)
}

/**
 * Holder secret (in [secrets], generated once, kept across re-enrolls) and the SBcred3 for the
 * current device key (public, in [kv]).
 */
class HolderStore(
    private val secrets: SecretStore,
    private val kv: KeyValue,
    private val random: (Int) -> ByteArray = ::secureRandomBytes,
) {
    fun secret(): ByteArray? = secrets.get(SECRET)?.takeIf { it.size == Holder.SECRET_LEN }

    fun loadOrCreate(): ByteArray {
        secret()?.let { return it }
        val s = random(Holder.SECRET_LEN)
        require(s.size == Holder.SECRET_LEN)
        secrets.put(SECRET, s)
        // read back: never send a commit to a secret we could not keep
        return secret()?.takeIf { it.contentEquals(s) } ?: error("holder secret did not persist")
    }

    fun commit(): Fe = Holder.commit(loadOrCreate())

    fun saveCredential(c: StoredCredential) {
        kv.set(K_CRED, c.cred.bytes.toB64())
        kv.set(K_SIG, c.sig.toB64())
        kv.set(K_ISSUER, c.issuerPub.toHex())
    }

    /** Stored credential, only if it is for [devicePub65] (when given) and well formed. */
    fun credential(devicePub65: ByteArray? = null): StoredCredential? {
        val c = runCatching {
            StoredCredential(Sbcred3(kv.get(K_CRED)!!.fromB64()), kv.get(K_SIG)!!.fromB64(), kv.get(K_ISSUER)!!.hexToBytes())
        }.getOrNull() ?: return null
        if (c.sig.size != 64 || c.issuerPub.size != 65) return null
        if (devicePub65 != null && !c.cred.devicePub64.contentEquals(devicePub65.copyOfRange(1, 65))) return null
        return c
    }

    fun clearCredential() {
        kv.set(K_CRED, null); kv.set(K_SIG, null); kv.set(K_ISSUER, null)
    }

    /** Full reset: secret and credential. */
    fun wipe() {
        clearCredential()
        secrets.delete(SECRET)
    }

    companion object {
        const val SECRET = "holder.v1"
        private const val K_CRED = "cred3.b64"
        private const val K_SIG = "cred3.sig"
        private const val K_ISSUER = "cred3.issuer"
    }
}

/** Unix seconds -> "YYYY-MM-DD" (UTC). */
fun formatUnixDay(s: Long): String {
    // Howard Hinnant's civil_from_days
    val z = s.floorDiv(86_400L) + 719_468
    val era = z.floorDiv(146_097L)
    val doe = z - era * 146_097
    val yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365
    val doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
    val mp = (5 * doy + 2) / 153
    val d = doy - (153 * mp + 2) / 5 + 1
    val m = if (mp < 10) mp + 3 else mp - 9
    val y = yoe + era * 400 + (if (m <= 2) 1 else 0)
    return "$y-${m.toString().padStart(2, '0')}-${d.toString().padStart(2, '0')}"
}
