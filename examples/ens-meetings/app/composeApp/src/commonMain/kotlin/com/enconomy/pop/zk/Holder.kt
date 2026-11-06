package com.enconomy.pop.zk

import com.enconomy.pop.ecdsaP256Verify
import com.enconomy.pop.fromB64
import com.enconomy.pop.hexToBytes
import com.enconomy.pop.toHex

/**
 * Holder secret and SBcred3 (optionA-v2 build_fixtures_popt2.py, port spec §1).
 *
 * secret  31 random bytes, BE integer < 2^248 (always < p). Never leaves the phone.
 * commit  Poseidon7 sponge16(TAG_HOLD, [secret]), 32 bytes BE. Sent at enroll.
 * cred    "SBcred3" || X || Y || expiry u64 BE (unix s) || holder_commit     (111 bytes)
 * sig     issuer ES256 over sha256(cred), raw r||s.
 */
object Holder {
    const val SECRET_LEN = 31

    fun secretFe(secret: ByteArray): Fe {
        require(secret.size == SECRET_LEN) { "holder secret must be $SECRET_LEN bytes" }
        return Fe.fromBytes(ByteArray(1) + secret)
    }

    fun commit(secret: ByteArray): Fe = Poseidon7.hash16(Poseidon7.TAG_HOLD, listOf(secretFe(secret)))
}

class Sbcred3(val bytes: ByteArray) {
    init {
        require(bytes.size == LEN && bytes.copyOf(7).contentEquals(MAGIC)) { "not an SBcred3" }
    }

    /** X || Y, no 0x04. */
    val devicePub64: ByteArray get() = bytes.copyOfRange(7, 71)
    val expiry: Long get() = (71 until 79).fold(0L) { a, i -> (a shl 8) or (bytes[i].toLong() and 0xff) }
    val holderCommit: ByteArray get() = bytes.copyOfRange(79, 111)

    companion object {
        const val LEN = 111
        val MAGIC = "SBcred3".encodeToByteArray()

        fun build(pub65: ByteArray, expiry: Long, holderCommit: ByteArray): Sbcred3 {
            require(pub65.size == 65 && pub65[0] == 4.toByte()) { "pub must be SEC1 uncompressed" }
            require(holderCommit.size == 32) { "holder_commit must be 32 bytes" }
            val e = ByteArray(8) { (expiry ushr (56 - 8 * it)).toByte() }
            return Sbcred3(MAGIC + pub65.copyOfRange(1, 65) + e + holderCommit)
        }
    }
}

/** What the phone keeps: credential, issuer signature, and the issuer it was checked against. */
class StoredCredential(val cred: Sbcred3, /** raw r||s */ val sig: ByteArray, /** 04||X||Y */ val issuerPub: ByteArray) {
    val expiry: Long get() = cred.expiry
}

class CredentialException(val reason: String, msg: String) : Exception("$reason: $msg")

/**
 * Checks an enroll response credential before storing it: format, the key and commit we sent,
 * issuer == the one /v1/config pinned, and the issuer signature.
 */
fun acceptCredential(
    format: String,
    credB64: String,
    sigB64: String,
    expiry: Long,
    issuerPubHex: String?,
    pinnedIssuer: ByteArray,
    devicePub65: ByteArray,
    holderCommit: ByteArray,
): StoredCredential {
    fun bad(r: String, m: String): Nothing = throw CredentialException(r, m)
    if (format != "SBcred3") bad("bad_format", format)
    val cred = runCatching { Sbcred3(credB64.fromB64()) }.getOrElse { bad("bad_format", "not an SBcred3") }
    val sig = runCatching { sigB64.fromB64() }.getOrNull()
    if (sig == null || sig.size != 64) bad("bad_sig", "issuer signature must be 64 bytes")
    if (!cred.devicePub64.contentEquals(devicePub65.copyOfRange(1, 65))) bad("wrong_key", "credential is for another key")
    if (!cred.holderCommit.contentEquals(holderCommit)) bad("wrong_commit", "credential holder_commit != ours")
    if (cred.expiry != expiry) bad("bad_expiry", "expiry ${cred.expiry} != $expiry")
    if (issuerPubHex != null) {
        val claimed = runCatching { issuerPubHex.hexToBytes() }.getOrNull()
        if (claimed == null || !claimed.contentEquals(pinnedIssuer)) bad("issuer_unknown", "issuer ${issuerPubHex.take(16)} != /v1/config")
    }
    if (!ecdsaP256Verify(pinnedIssuer, cred.bytes, sig)) bad("issuer_unknown", "issuer signature invalid (${pinnedIssuer.toHex().take(16)})")
    return StoredCredential(cred, sig, pinnedIssuer)
}
