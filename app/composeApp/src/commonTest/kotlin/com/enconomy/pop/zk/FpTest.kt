package com.enconomy.pop.zk

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class FpTest {
    private val pHex = "ffffffff00000001000000000000000000000000ffffffffffffffffffffffff"

    @Test fun codec() {
        assertEquals(pHex, ZkVectors.str(ZkVectors.p7, "p"))
        val h = "00f3fb80e94945e7b612b469eb5968ea2895b5ec2bf739921971696650ada72a"
        val x = Fe.fromHex("0x" + h.trimStart('0'))
        assertEquals(h, x.toHex())
        assertEquals(x, Fe.fromBytes(x.toBytes()))
        assertEquals("0000000000000000000000000000000000000000000000000000000000000007", Fe.of(7).toHex())
        assertEquals("ffffffff00000001000000000000000000000000fffffffffffffffffffffffe", Fe.of(-1).toHex())
        assertEquals("ffffffff00000001000000000000000000000000ffffffffffffffff7fffffff", Fe.of(-(1L shl 31)).toHex())
        assertEquals("ffffffff00000001000000000000000000000000ffffffff7fffffffffffffff", Fe.of(Long.MIN_VALUE).toHex())
        assertFailsWith<IllegalArgumentException> { Fe.fromHex(pHex) }
        assertFailsWith<IllegalArgumentException> { Fe.fromBytes(ByteArray(31)) }
    }

    /** Montgomery round trip and a·b against small integers, and edge values near p. */
    @Test fun arithmetic() {
        val t = LongArray(Fp.N + 2)
        fun mont(x: Fe) = LongArray(Fp.N).also { Fp.toMont(it, 0, x.w, 0, t) }
        fun plain(m: LongArray) = Fe(LongArray(Fp.N).also { Fp.fromMont(it, 0, m, 0, t) })
        fun mul(a: Fe, b: Fe) = plain(LongArray(Fp.N).also { Fp.mul(it, 0, mont(a), 0, mont(b), 0, t) })
        fun add(a: Fe, b: Fe) = plain(LongArray(Fp.N).also { Fp.add(it, 0, mont(a), 0, mont(b), 0) })
        val m1 = Fe.of(-1)
        for (x in listOf(Fe.ZERO, Fe.of(1), Fe.of(123456789), m1)) assertEquals(x, plain(mont(x)))
        assertEquals(Fe.of(1), mul(m1, m1))
        assertEquals(Fe.of(-2), add(m1, m1))
        assertEquals(Fe.ZERO, add(m1, Fe.of(1)))
        assertEquals(Fe.of(3037000499L * 3037000499L), mul(Fe.of(3037000499L), Fe.of(3037000499L)))
        assertEquals(Fe.of(-6), mul(Fe.of(-2), Fe.of(3)))
        // (2^255)·2 = 2^256 ≡ 2^224 - 2^192 - 2^96 + 1
        val two255 = Fe.fromHex("8" + "0".repeat(63))
        assertEquals("00000000fffffffeffffffffffffffffffffffff000000000000000000000001", mul(two255, Fe.of(2)).toHex())
    }
}
