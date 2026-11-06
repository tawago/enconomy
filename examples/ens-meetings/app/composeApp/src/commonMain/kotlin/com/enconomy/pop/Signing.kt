package com.enconomy.pop

/** Contract §2.1. Hardware key on Android; fakes in tests. */
interface DeviceKey {
    /** SEC1 uncompressed, 65 bytes 04||X||Y. */
    val pubkey: ByteArray
    /** "strongbox" | "tee" | "secure_enclave" (iOS) | "software" | "unknown" */
    val securityLevel: String
    /** SHA256withECDSA over [message]; raw r||s, 64 bytes. Blocking (StrongBox can take ~100 ms). */
    fun sign(message: ByteArray): ByteArray

    val deviceId: String get() = deviceIdOf(pubkey)
}

class GeneratedKey(
    val key: DeviceKey,
    /** DER certs leaf..root, null if the platform gave none. */ val chain: List<ByteArray>?,
    /** iOS App Attest, null elsewhere or when unavailable. */ val appAttest: AppAttestation? = null,
)

/**
 * DCAppAttestService output. The attested key is a separate App Attest key; it binds the device key
 * through clientDataHash = sha256(nonce32 || sha256(pubkey65)).
 */
class AppAttestation(/** base64 std, as returned by generateKey. */ val keyId: String, /** CBOR attestation object. */ val attestation: ByteArray)

interface DeviceKeystore {
    /** Enroll `platform` (§2.2.1). */
    val platform: String get() = "android"
    fun load(): DeviceKey?
    /** Replaces any existing key. [challenge] = enroll nonce bytes (attestation challenge). */
    fun generate(challenge: ByteArray): GeneratedKey
    fun delete()
}

const val KEY_ALIAS = "pop-device-v1"

/** hex of sha256(pubkey65)[:16]. */
fun deviceIdOf(pubkey65: ByteArray): String = sha256(pubkey65).copyOf(16).toHex()

/** DER ECDSA-Sig-Value -> raw r||s, each 32 bytes big-endian. */
fun derToRawRs(der: ByteArray, n: Int = 32): ByteArray {
    var i = 0
    fun len(): Int {
        val b = der[i++].toInt() and 0xff
        if (b < 0x80) return b
        var l = 0
        repeat(b and 0x7f) { l = (l shl 8) or (der[i++].toInt() and 0xff) }
        return l
    }
    fun int(): ByteArray {
        require(der[i++] == 0x02.toByte()) { "bad DER int" }
        val l = len()
        var v = der.copyOfRange(i, i + l)
        i += l
        var s = 0
        while (s < v.size - 1 && v[s] == 0.toByte()) s++
        v = v.copyOfRange(s, v.size)
        require(v.size <= n) { "int too long" }
        return ByteArray(n - v.size) + v
    }
    require(der[i++] == 0x30.toByte()) { "bad DER seq" }
    len()
    return int() + int()
}

/** §2.3 message: pop-req-v1\nMETHOD\nPATH?QUERY\nsha256hex(body)\nts */
fun requestMessage(method: String, pathAndQuery: String, body: ByteArray, tsMs: Long): ByteArray =
    "pop-req-v1\n${method.uppercase()}\n$pathAndQuery\n${sha256(body).toHex()}\n$tsMs".encodeToByteArray()

data class AuthHeaders(val device: String, val ts: String, val sig: String)

fun signRequest(key: DeviceKey, method: String, pathAndQuery: String, body: ByteArray, tsMs: Long): AuthHeaders =
    AuthHeaders(key.deviceId, tsMs.toString(), key.sign(requestMessage(method, pathAndQuery, body, tsMs)).toB64())
