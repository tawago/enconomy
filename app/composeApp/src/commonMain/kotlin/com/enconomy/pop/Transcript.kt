package com.enconomy.pop

/**
 * Contract §7. Fixed-length big-endian records, no length prefixes. Python twin: server/pop/codec.py.
 * Golden vector (same literals both sides): server/tests/test_transcript_codec.py,
 * app commonTest TranscriptCodecTest.
 */
data class Transcript(
    val role: Char,
    val attempt: Int,
    val sessionNonce: ByteArray,
    val pkSelf: ByteArray,
    val pkPartner: ByteArray,
    val sampleRate: Int,
    val half: Int,
    val recSha256: ByteArray,
    val playFramePosition: Long,
    val playNanoTime: Long,
    val recFrame0NanoTime: Long,
    val selfOsDelta: Int,
    val commitHash: ByteArray,
) {
    fun encode(): ByteArray = TranscriptCodec.transcript(this)
}

/**
 * POPT v2 (docs/pop-transcript-v2.md §1). Implied, not stored: p_self = a_self − self_os_delta,
 * a_partner = a_self + half (A) / a_self − half (B).
 */
data class Transcript2(
    val role: Char,
    val attempt: Int,
    val sessionNonce: ByteArray,
    val pkSelf: ByteArray,
    val pkPartner: ByteArray,
    val sampleRate: Int,
    val half: Int,
    /** Poseidon7 rec_root, 32 bytes BE (< p). */
    val recRoot: ByteArray,
    val playFramePosition: Long,
    val playNanoTime: Long,
    val recFrame0NanoTime: Long,
    val selfOsDelta: Int,
    val commitHash: ByteArray,
    val aSelf: Int,
    val pPartner: Int,
    val delta: Int,
    val codeCommit: ByteArray,
) {
    fun encode(): ByteArray = TranscriptCodec.transcript2(this)
    val pSelf: Int get() = aSelf - selfOsDelta
    val aPartner: Int get() = if (role == 'A') aSelf + half else aSelf - half
}

object TranscriptCodec {
    const val TRANSCRIPT_LEN = 269
    const val COMMIT_LEN = 71
    private const val VERSION: Byte = 1

    const val TRANSCRIPT2_LEN = 311
    private const val VERSION2: Byte = 2

    /**
     * §7.2: "POPC" | version | role | attempt u8 | session_nonce 32 | rec 32.
     * v1 rec = rec_sha256; v2 rec = rec_root (POPC v2, docs/pop-transcript-v2.md §4).
     */
    fun commit(role: Char, attempt: Int, nonce: ByteArray, rec: ByteArray, version: Int = 1): ByteArray {
        require(version == 1 || version == 2) { "version $version" }
        val w = W(COMMIT_LEN)
        w.bytes("POPC".encodeToByteArray()); w.u8(version); w.role(role); w.u8(attempt)
        w.fixed(nonce, 32); w.fixed(rec, 32)
        return w.done()
    }

    /** §7.1, 269 bytes. */
    fun transcript(t: Transcript): ByteArray {
        val w = W(TRANSCRIPT_LEN)
        w.bytes("POPT".encodeToByteArray()); w.u8(VERSION.toInt()); w.role(t.role); w.u8(t.attempt)
        w.fixed(t.sessionNonce, 32); w.fixed(t.pkSelf, 65); w.fixed(t.pkPartner, 65)
        require(t.sampleRate > 0) { "sample_rate" }
        w.be(t.sampleRate.toLong(), 4); w.be(t.half.toLong(), 4)
        w.fixed(t.recSha256, 32)
        require(t.playFramePosition >= 0 && t.playNanoTime >= 0 && t.recFrame0NanoTime >= 0) { "u64 fields must be >= 0" }
        w.be(t.playFramePosition, 8); w.be(t.playNanoTime, 8); w.be(t.recFrame0NanoTime, 8)
        w.be(t.selfOsDelta.toLong(), 4)
        w.fixed(t.commitHash, 32)
        return w.done()
    }

    fun decodeTranscript(b: ByteArray): Transcript {
        require(b.size == TRANSCRIPT_LEN) { "transcript must be $TRANSCRIPT_LEN bytes, got ${b.size}" }
        require(b.copyOfRange(0, 4).decodeToString() == "POPT" && b[4] == VERSION) { "bad magic/version" }
        val role = b[5].toInt().toChar()
        require(role == 'A' || role == 'B') { "bad role" }
        fun be(off: Int, n: Int): Long { var v = 0L; for (i in 0 until n) v = (v shl 8) or (b[off + i].toLong() and 0xff); return v }
        return Transcript(
            role = role, attempt = b[6].toInt() and 0xff,
            sessionNonce = b.copyOfRange(7, 39), pkSelf = b.copyOfRange(39, 104), pkPartner = b.copyOfRange(104, 169),
            sampleRate = be(169, 4).toInt(), half = be(173, 4).toInt(), recSha256 = b.copyOfRange(177, 209),
            playFramePosition = be(209, 8), playNanoTime = be(217, 8), recFrame0NanoTime = be(225, 8),
            selfOsDelta = be(233, 4).toInt(), commitHash = b.copyOfRange(237, 269),
        )
    }

    /** POPT v2, 311 bytes: v1 layout with version 2 and rec_root at [177:209], then a_self u32 | p_partner u32 | delta u16 | code_commit 32. */
    fun transcript2(t: Transcript2): ByteArray {
        val w = W(TRANSCRIPT2_LEN)
        w.bytes("POPT".encodeToByteArray()); w.u8(VERSION2.toInt()); w.role(t.role); w.u8(t.attempt)
        w.fixed(t.sessionNonce, 32); w.fixed(t.pkSelf, 65); w.fixed(t.pkPartner, 65)
        require(t.sampleRate > 0) { "sample_rate" }
        w.be(t.sampleRate.toLong(), 4); w.be(t.half.toLong(), 4)
        w.fixed(t.recRoot, 32)
        require(t.playFramePosition >= 0 && t.playNanoTime >= 0 && t.recFrame0NanoTime >= 0) { "u64 fields must be >= 0" }
        w.be(t.playFramePosition, 8); w.be(t.playNanoTime, 8); w.be(t.recFrame0NanoTime, 8)
        w.be(t.selfOsDelta.toLong(), 4)
        w.fixed(t.commitHash, 32)
        require(t.aSelf >= 0 && t.pPartner >= 0) { "a_self / p_partner are u32" }
        require(t.delta in 0..0xffff) { "delta u16" }
        w.be(t.aSelf.toLong(), 4); w.be(t.pPartner.toLong(), 4); w.be(t.delta.toLong(), 2)
        w.fixed(t.codeCommit, 32)
        return w.done()
    }

    fun decodeTranscript2(b: ByteArray): Transcript2 {
        require(b.size == TRANSCRIPT2_LEN) { "transcript v2 must be $TRANSCRIPT2_LEN bytes, got ${b.size}" }
        require(b.copyOfRange(0, 4).decodeToString() == "POPT" && b[4] == VERSION2) { "bad magic/version" }
        val role = b[5].toInt().toChar()
        require(role == 'A' || role == 'B') { "bad role" }
        fun be(off: Int, n: Int): Long { var v = 0L; for (i in 0 until n) v = (v shl 8) or (b[off + i].toLong() and 0xff); return v }
        return Transcript2(
            role = role, attempt = b[6].toInt() and 0xff,
            sessionNonce = b.copyOfRange(7, 39), pkSelf = b.copyOfRange(39, 104), pkPartner = b.copyOfRange(104, 169),
            sampleRate = be(169, 4).toInt(), half = be(173, 4).toInt(), recRoot = b.copyOfRange(177, 209),
            playFramePosition = be(209, 8), playNanoTime = be(217, 8), recFrame0NanoTime = be(225, 8),
            selfOsDelta = be(233, 4).toInt(), commitHash = b.copyOfRange(237, 269),
            aSelf = be(269, 4).toInt(), pPartner = be(273, 4).toInt(), delta = be(277, 2).toInt(),
            codeCommit = b.copyOfRange(279, 311),
        )
    }

    private class W(n: Int) {
        val b = ByteArray(n)
        var i = 0
        fun bytes(x: ByteArray) { x.copyInto(b, i); i += x.size }
        fun fixed(x: ByteArray, n: Int) { require(x.size == n) { "field needs $n bytes, got ${x.size}" }; bytes(x) }
        fun u8(v: Int) { require(v in 0..255) { "u8 $v" }; b[i++] = v.toByte() }
        fun role(r: Char) { require(r == 'A' || r == 'B') { "role $r" }; b[i++] = r.code.toByte() }
        fun be(v: Long, n: Int) { for (k in n - 1 downTo 0) b[i++] = (v ushr (8 * k)).toByte() }
        fun done(): ByteArray { check(i == b.size) { "wrote $i of ${b.size}" }; return b }
    }
}
