package com.enconomy.pop

import org.kotlincrypto.hash.sha3.Keccak256

/**
 * EIP-8141 signature scheme 2 (P256) helpers. Pure Kotlin, commonMain-safe (no BigInteger).
 *
 * Scheme 2 entry bytes = r || s || qx || qy (128). Rules the protocol and the sidecar check
 * (sidecar signature.ts validateSignature, P256 branch):
 *   0 < r < n, 0 < s <= n/2 (low-s), signer == keccak256(qx || qy)[12:],
 *   P256VERIFY(msg, r, s, qx, qy) with msg = sig_hash or an explicit nonzero 32-byte msg.
 * The 32 bytes go into ECDSA as the hash value e. No SHA-256 on top. So the phone has to sign
 * in digest mode (Android NONEwithECDSA, iOS ...DigestX962SHA256), never in message mode.
 */
object FrameSig {
    /** secp256r1 group order n. */
    val N: ByteArray = hex("ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551")
    /** floor(n / 2). s must be <= this. */
    val HALF_N: ByteArray = hex("7fffffff800000007fffffffffffffffde737d56d38bcf4279dce5617e3192a8")

    /** A frame-tx digest: sig_hash or an explicit msg. Exactly 32 bytes, not all zero. */
    fun requireDigest(d: ByteArray) {
        require(d.size == 32) { "digest must be 32 bytes, got ${d.size}" }
        require(d.any { it != 0.toByte() }) { "zero digest is invalid as explicit msg" }
    }

    fun isLowS(s32: ByteArray): Boolean = cmp(s32, HALF_N) <= 0

    /** r || s (64) -> r || min(s, n - s). Same signature, other sign of the point. Idempotent. */
    fun normalizeLowS(rs: ByteArray): ByteArray {
        require(rs.size == 64) { "r||s must be 64 bytes" }
        val r = rs.copyOfRange(0, 32)
        val s = rs.copyOfRange(32, 64)
        require(cmp(s, ZERO) > 0 && cmp(s, N) < 0) { "s out of range" }
        return if (isLowS(s)) rs.copyOf() else r + sub(N, s)
    }

    /** 65-byte 04||X||Y -> X||Y. */
    fun qxqy(pub65: ByteArray): ByteArray {
        require(pub65.size == 65 && pub65[0] == 4.toByte()) { "pubkey must be SEC1 uncompressed P-256" }
        return pub65.copyOfRange(1, 65)
    }

    /** Scheme-2 signer address: keccak256(qx || qy)[12:], 20 bytes. */
    fun signer(pub65: ByteArray): ByteArray = Keccak256().digest(qxqy(pub65)).copyOfRange(12, 32)

    fun signerHex(pub65: ByteArray): String = "0x" + signer(pub65).hexStr()

    /** The 128-byte `signature` field of a scheme-2 entry. Refuses high-s, so a forgotten normalize fails here, not at the mempool. */
    fun scheme2Bytes(rs: ByteArray, pub65: ByteArray): ByteArray {
        require(rs.size == 64) { "r||s must be 64 bytes" }
        require(isLowS(rs.copyOfRange(32, 64))) { "high s: call normalizeLowS first" }
        return rs + qxqy(pub65)
    }

    // ---- 256-bit big-endian helpers ----

    private val ZERO = ByteArray(32)

    /** Unsigned compare of two 32-byte big-endian numbers. */
    internal fun cmp(a: ByteArray, b: ByteArray): Int {
        require(a.size == 32 && b.size == 32)
        for (i in 0 until 32) {
            val x = a[i].toInt() and 0xff
            val y = b[i].toInt() and 0xff
            if (x != y) return x - y
        }
        return 0
    }

    /** a - b, requires a >= b. */
    internal fun sub(a: ByteArray, b: ByteArray): ByteArray {
        require(cmp(a, b) >= 0)
        val out = ByteArray(32)
        var borrow = 0
        for (i in 31 downTo 0) {
            var d = (a[i].toInt() and 0xff) - (b[i].toInt() and 0xff) - borrow
            borrow = if (d < 0) { d += 256; 1 } else 0
            out[i] = d.toByte()
        }
        return out
    }

    private fun hex(h: String): ByteArray = ByteArray(h.length / 2) { h.substring(2 * it, 2 * it + 2).toInt(16).toByte() }
    private fun ByteArray.hexStr(): String = joinToString("") { (it.toInt() and 0xff).toString(16).padStart(2, '0') }
}

/**
 * A key that signs raw 32-byte digests for frame transactions. Android: its own alias
 * (pop-frame-v1, DIGEST_NONE+SHA256). iOS: the same Secure Enclave key as DeviceKey.
 */
interface FrameKey {
    /** 65 bytes 04||X||Y. */
    val pubkey: ByteArray
    val securityLevel: String
    /** ECDSA over [digest32] as-is (no hashing). Raw r||s, 64 bytes, already low-s. Blocking. */
    fun signDigest(digest32: ByteArray): ByteArray

    /** keccak256(qx||qy)[12:], the scheme-2 signer and the registry's device address. */
    val signerAddress: String get() = FrameSig.signerHex(pubkey)
}
