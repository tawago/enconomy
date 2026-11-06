package com.enconomy.pop

import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** Golden vector shared with server/tests/test_transcript_codec.py (VEC, VEC_SHA, COMMIT_SHA). */
class TranscriptCodecTest {
    private val nonce = ByteArray(32) { it.toByte() }
    private val vec = Transcript(
        role = 'A', attempt = 1, sessionNonce = nonce,
        pkSelf = byteArrayOf(4) + ByteArray(64) { 0x11 }, pkPartner = byteArrayOf(4) + ByteArray(64) { 0x22 },
        sampleRate = 48000, half = -45566, recSha256 = ByteArray(32) { 0x33 },
        playFramePosition = 26400, playNanoTime = 123456789012345, recFrame0NanoTime = 123456000000000,
        selfOsDelta = -7, commitHash = ByteArray(32) { 0x44 },
    )

    @Test fun knownVector() {
        val raw = vec.encode()
        assertEquals(269, raw.size)
        assertEquals("40e85cdceed6bea79673f2cc017f89b248e9b0e20bbb2fdf88b4d8d3b6756e35", sha256(raw).toHex())
        assertEquals("POPT", raw.copyOfRange(0, 4).decodeToString())
        assertEquals(1, raw[4].toInt()); assertEquals(0x41, raw[5].toInt()); assertEquals(1, raw[6].toInt())
        assertContentEquals(nonce, raw.copyOfRange(7, 39))
        assertContentEquals(vec.pkSelf, raw.copyOfRange(39, 104))
        assertContentEquals(vec.pkPartner, raw.copyOfRange(104, 169))
        assertContentEquals(ByteArray(32) { 0x44 }, raw.copyOfRange(237, 269))
        val d = TranscriptCodec.decodeTranscript(raw)
        assertEquals(-45566, d.half); assertEquals(-7, d.selfOsDelta); assertEquals(48000, d.sampleRate)
        assertEquals(123456789012345, d.playNanoTime); assertEquals(26400, d.playFramePosition)
        assertContentEquals(raw, d.encode())
    }

    @Test fun commitVector() {
        val c = TranscriptCodec.commit('B', 0, nonce, ByteArray(32) { 0x33 })
        assertEquals(71, c.size)
        assertEquals("4678fcbfe517fb8c207fe6b01d481632e4d1b4475c4eb11b0455816f0866e9a6", sha256(c).toHex())
        assertContentEquals("POPC".encodeToByteArray() + byteArrayOf(1, 0x42, 0), c.copyOfRange(0, 7))
    }

    @Test fun rejects() {
        assertFailsWith<IllegalArgumentException> { vec.copy(pkSelf = ByteArray(64)).encode() }
        assertFailsWith<IllegalArgumentException> { vec.copy(role = 'C').encode() }
        assertFailsWith<IllegalArgumentException> { vec.copy(attempt = 256).encode() }
        assertFailsWith<IllegalArgumentException> { TranscriptCodec.decodeTranscript(vec.encode().copyOf(268)) }
    }
}
