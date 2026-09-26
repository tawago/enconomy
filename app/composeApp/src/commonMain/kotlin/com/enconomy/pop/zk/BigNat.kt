package com.enconomy.pop.zk

/**
 * Small unsigned big integer for the witness input (decimal strings, s⁻¹ mod n). Not constant time:
 * only public values and signature scalars that the proof hides anyway go through it.
 * Limbs are 32-bit, little-endian, in Longs.
 */
class BigNat private constructor(private val d: LongArray) : Comparable<BigNat> {
    private val len: Int = run { var n = d.size; while (n > 0 && d[n - 1] == 0L) n--; n }

    val isZero: Boolean get() = len == 0

    override fun compareTo(other: BigNat): Int {
        if (len != other.len) return len.compareTo(other.len)
        for (i in len - 1 downTo 0) if (d[i] != other.d[i]) return d[i].compareTo(other.d[i])
        return 0
    }

    override fun equals(other: Any?): Boolean = other is BigNat && compareTo(other) == 0
    override fun hashCode(): Int = d.copyOf(len).contentHashCode()

    operator fun plus(o: BigNat): BigNat {
        val n = maxOf(len, o.len) + 1
        val r = LongArray(n)
        var c = 0L
        for (i in 0 until n) {
            val v = limb(i) + o.limb(i) + c
            r[i] = v and MASK; c = v ushr 32
        }
        return BigNat(r)
    }

    /** this − o, requires this ≥ o. */
    operator fun minus(o: BigNat): BigNat {
        require(this >= o) { "negative BigNat" }
        val r = LongArray(len)
        var b = 0L
        for (i in 0 until len) {
            var v = limb(i) - o.limb(i) - b
            b = if (v < 0) { v += 1L shl 32; 1 } else 0
            r[i] = v
        }
        return BigNat(r)
    }

    operator fun times(o: BigNat): BigNat {
        val r = LongArray(len + o.len + 1)
        for (i in 0 until len) {
            var c = 0L
            val a = d[i]
            for (j in 0 until o.len) {
                val t = a * o.d[j] // < 2^64 unsigned; split to stay in range
                val lo = (t and MASK) + r[i + j] + c
                r[i + j] = lo and MASK
                c = (t ushr 32) + (lo ushr 32)
            }
            var k = i + o.len
            while (c != 0L) { val v = r[k] + c; r[k] = v and MASK; c = v ushr 32; k++ }
        }
        return BigNat(r)
    }

    /** this mod m (shift-subtract; fine for a few hundred bits). */
    operator fun rem(m: BigNat): BigNat {
        require(!m.isZero)
        if (this < m) return this
        var r = ZERO
        for (bit in bitLength() - 1 downTo 0) {
            r = r.shl1(testBit(bit))
            if (r >= m) r -= m
        }
        return r
    }

    fun modPow(e: BigNat, m: BigNat): BigNat {
        var r = ONE % m
        val b = this % m
        for (bit in e.bitLength() - 1 downTo 0) {
            r = (r * r) % m
            if (e.testBit(bit)) r = (r * b) % m
        }
        return r
    }

    /** Inverse mod a prime [p] (Fermat). */
    fun modInversePrime(p: BigNat): BigNat {
        val a = this % p
        require(!a.isZero) { "no inverse of 0" }
        return a.modPow(p - TWO, p)
    }

    fun bitLength(): Int = if (len == 0) 0 else 32 * (len - 1) + (64 - d[len - 1].countLeadingZeroBits())

    fun testBit(i: Int): Boolean = (limb(i / 32) ushr (i % 32)) and 1L == 1L

    private fun limb(i: Int): Long = if (i < len) d[i] else 0L

    private fun shl1(bit: Boolean): BigNat {
        val r = LongArray(len + 1)
        var c = if (bit) 1L else 0L
        for (i in 0 until len) {
            val v = (d[i] shl 1) or c
            r[i] = v and MASK; c = v ushr 32
        }
        r[len] = c
        return BigNat(r)
    }

    fun toDecimal(): String {
        if (len == 0) return "0"
        val w = d.copyOf(len)
        var n = len
        val parts = ArrayList<Int>()
        while (n > 0) {
            var rem = 0L
            for (i in n - 1 downTo 0) {
                val cur = (rem shl 32) or w[i]
                w[i] = cur / 1_000_000_000L
                rem = cur % 1_000_000_000L
            }
            parts += rem.toInt()
            while (n > 0 && w[n - 1] == 0L) n--
        }
        val sb = StringBuilder(parts.last().toString())
        for (i in parts.size - 2 downTo 0) sb.append(parts[i].toString().padStart(9, '0'))
        return sb.toString()
    }

    /** Big-endian, exactly [n] bytes. */
    fun toBytes(n: Int = 32): ByteArray {
        require(bitLength() <= 8 * n) { "BigNat does not fit $n bytes" }
        return ByteArray(n) { k -> val i = n - 1 - k; (limb(i / 4) ushr (8 * (i % 4))).toByte() }
    }

    override fun toString(): String = toDecimal()

    companion object {
        private const val MASK = 0xFFFFFFFFL
        val ZERO = BigNat(LongArray(0))
        val ONE = of(1)
        val TWO = of(2)

        fun of(v: Long): BigNat {
            require(v >= 0) { "BigNat.of($v)" }
            return BigNat(longArrayOf(v and MASK, v ushr 32))
        }

        /** Unsigned big-endian bytes. */
        fun fromBytes(b: ByteArray): BigNat {
            val n = (b.size + 3) / 4
            val r = LongArray(n)
            for (k in b.indices) {
                val i = b.size - 1 - k
                r[i / 4] = r[i / 4] or ((b[k].toLong() and 0xff) shl (8 * (i % 4)))
            }
            return BigNat(r)
        }

        fun fromHex(h: String): BigNat {
            val s = h.removePrefix("0x")
            return fromBytes((if (s.length % 2 == 1) "0$s" else s).chunked(2).map { it.toInt(16).toByte() }.toByteArray())
        }

        /** P-256 base field p (= circuit field). */
        val P = fromHex("FFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF")

        /** P-256 group order n (ECDSA). */
        val N = fromHex("FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551")
    }
}
