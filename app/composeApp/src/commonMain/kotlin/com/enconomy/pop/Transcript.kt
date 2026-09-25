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

object TranscriptCodec {
    const val TRANSCRIPT_LEN = 269
    const val COMMIT_LEN = 71
    private const val VERSION: Byte = 1

    /** §7.2: "POPC" | 0x01 | role | attempt u8 | session_nonce 32 | rec_sha256 32. */
    fun commit(role: Char, attempt: Int, nonce: ByteArray, recSha256: ByteArray): ByteArray {
        val w = W(COMMIT_LEN)
        w.bytes("POPC".encodeToByteArray()); w.u8(VERSION.toInt()); w.role(role); w.u8(attempt)
        w.fixed(nonce, 32); w.fixed(recSha256, 32)
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
