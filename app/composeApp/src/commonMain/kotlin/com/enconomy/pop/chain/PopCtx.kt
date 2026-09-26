package com.enconomy.pop.chain

import com.enconomy.pop.hexToBytes
import com.enconomy.pop.toHex
import org.kotlincrypto.hash.sha3.Keccak256

/**
 * PopCtx (docs/worldid/01 §5): the one context-binding formula.
 *
 *   session_nonce = keccak256(abi.encode(bytes32 DOMAIN, uint256 chainId, address consumer,
 *                                        bytes32 ctxHash, uint64 notBefore, bytes16 sid))
 *   signal        = session_nonce ‖ role (33 B, role 'A' 0x41 | 'B' 0x42)
 *   signalHash    = uint256(keccak256(signal)) >> 8
 *
 * The 192-byte preimage is built by hand as six 32-byte words; no ABI library.
 */
object PopCtx {
    const val PREIMAGE_LEN = 192

    fun keccak(b: ByteArray): ByteArray = Keccak256().digest(b)

    /** keccak256("pop-ctx-v1"), the hash, not the string. */
    val DOMAIN: ByteArray = keccak("pop-ctx-v1".encodeToByteArray())

    fun preimage(chainId: Long, consumer: ByteArray, ctxHash: ByteArray, notBefore: Long, sid: ByteArray): ByteArray {
        require(chainId >= 0) { "chainId < 0" }
        require(consumer.size == 20) { "consumer must be 20 bytes" }
        require(ctxHash.size == 32) { "ctxHash must be 32 bytes" }
        require(notBefore >= 0) { "notBefore < 0" }
        require(sid.size == 16) { "sid must be 16 bytes" }
        val out = ByteArray(PREIMAGE_LEN)
        DOMAIN.copyInto(out, 0)                    // word 0
        putBe(out, 64, chainId)                   // word 1: uint256, left zero pad
        consumer.copyInto(out, 64 + 12)           // word 2: 12 zero bytes ‖ address
        ctxHash.copyInto(out, 96)                 // word 3
        putBe(out, 160, notBefore)                // word 4: uint64, left zero pad
        sid.copyInto(out, 160)                    // word 5: bytes16 left-aligned, right zero pad
        check(out.size == PREIMAGE_LEN)
        return out
    }

    fun nonce(chainId: Long, consumer: ByteArray, ctxHash: ByteArray, notBefore: Long, sid: ByteArray): ByteArray =
        keccak(preimage(chainId, consumer, ctxHash, notBefore, sid))

    /** Wire form: consumer "0x"+40 hex, ctxHash "0x"+64 hex, sessionId 32 hex (no prefix). Returns 32 bytes. */
    fun nonce(chainId: Long, consumer: String, ctxHash: String, notBefore: Long, sessionId: String): ByteArray =
        nonce(chainId, hex0x(consumer, 20), hex0x(ctxHash, 32), notBefore, hexN(sessionId.removePrefix("0x"), 16))

    fun signal(nonce: ByteArray, role: Char): ByteArray {
        require(nonce.size == 32) { "nonce must be 32 bytes" }
        require(role == 'A' || role == 'B') { "role must be A or B" }
        return nonce + byteArrayOf(role.code.toByte())
    }

    /** The IDKit signal string: lowercase "0x" + 66 hex, so IDKit decodes it to raw bytes. */
    fun signalHex(nonce: ByteArray, role: Char): String = "0x" + signal(nonce, role).toHex()

    /** uint256(keccak256(b)) >> 8 as "0x%064x". */
    fun fieldHash(b: ByteArray): String = "0x00" + keccak(b).copyOf(31).toHex()

    fun signalHash(nonce: ByteArray, role: Char): String = fieldHash(signal(nonce, role))

    fun action(sessionId: String): String = "pop:$sessionId"

    fun actionField(action: String): String = fieldHash(action.encodeToByteArray())

    /** Big-endian [v] in the 32-byte word that ends at [end] (exclusive). */
    private fun putBe(out: ByteArray, end: Int, v: Long) {
        for (i in 0 until 8) out[end - 1 - i] = (v ushr (8 * i)).toByte()
    }

    private fun hex0x(s: String, n: Int): ByteArray {
        require(s.startsWith("0x") || s.startsWith("0X")) { "missing 0x" }
        return hexN(s.substring(2), n)
    }

    private fun hexN(s: String, n: Int): ByteArray {
        require(s.length == 2 * n && s.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }) { "want $n hex bytes" }
        return s.lowercase().hexToBytes()
    }
}
