package com.enconomy.pop

import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals

/** Deterministic stand-in: "signature" = sha256(msg) || sha256(sha256(msg)). */
class FakeKey(override val pubkey: ByteArray = byteArrayOf(4) + ByteArray(64) { (it + 1).toByte() }) : DeviceKey {
    override val securityLevel = "software"
    val signed = mutableListOf<ByteArray>()
    override fun sign(message: ByteArray): ByteArray {
        signed += message
        val h = sha256(message)
        return h + sha256(h)
    }
}

class SigningTest {
    @Test fun deviceId() {
        assertEquals("0ed3a6ab957ff6f59a9630a473d31a7d", FakeKey().deviceId)
    }

    @Test fun requestMessageLayout() {
        val m = requestMessage("post", "/v1/session/ab/join?x=1", """{"join_token":"t"}""".encodeToByteArray(), 1790000000000)
        val s = m.decodeToString()
        assertEquals(5, s.split("\n").size)
        assertEquals("pop-req-v1\nPOST\n/v1/session/ab/join?x=1\n", s.substringBeforeLast("\n").substringBeforeLast("\n") + "\n")
        assertEquals("e8bb182f763748ced75b9557a2f54d628d1eaeaae72a66cc74dba37649ce168e", sha256(m).toHex())
        val empty = requestMessage("GET", "/v1/time", ByteArray(0), 1).decodeToString()
        assertEquals("pop-req-v1\nGET\n/v1/time\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n1", empty)
    }

    @Test fun derToRaw() {
        val r = ByteArray(32) { 0x11 }
        val s = ByteArray(32) { 0x22 }
        // r with high bit -> 33 bytes with leading 0; s short (31 bytes)
        val rHi = ByteArray(32) { if (it == 0) 0x80.toByte() else 0x11 }
        val sShort = ByteArray(31) { 0x22 }
        val der = byteArrayOf(0x30, (2 + 33 + 2 + 31).toByte(), 0x02, 33, 0) + rHi + byteArrayOf(0x02, 31) + sShort
        val raw = derToRawRs(der)
        assertEquals(64, raw.size)
        assertContentEquals(rHi, raw.copyOfRange(0, 32))
        assertContentEquals(byteArrayOf(0) + sShort, raw.copyOfRange(32, 64))
        val plain = byteArrayOf(0x30, 68, 0x02, 32) + r + byteArrayOf(0x02, 32) + s
        assertContentEquals(r + s, derToRawRs(plain))
    }
}
