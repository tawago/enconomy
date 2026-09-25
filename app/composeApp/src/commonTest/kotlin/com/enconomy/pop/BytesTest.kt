package com.enconomy.pop

import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals

class BytesTest {
    @Test fun sha256Vectors() {
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", sha256(ByteArray(0)).toHex())
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", sha256("abc".encodeToByteArray()).toHex())
        assertEquals(
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
            sha256("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq".encodeToByteArray()).toHex(),
        )
        assertEquals(
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
            sha256(ByteArray(1_000_000) { 'a'.code.toByte() }).toHex(),
        )
    }

    @Test fun hexAndBase64() {
        val b = byteArrayOf(0, 1, 0x7f, -1, -128)
        assertEquals("00017fff80", b.toHex())
        assertContentEquals(b, "00017fff80".hexToBytes())
        assertContentEquals(b, b.toB64().fromB64())
        assertContentEquals(b, b.toB64Url().fromB64Url())
        assertEquals("AAF__4A", b.toB64Url())
    }

    @Test fun testResourcesOnClasspath() {
        assertEquals("pop test resources ok", readTestResource("pop/smoke.txt").trim())
    }
}
