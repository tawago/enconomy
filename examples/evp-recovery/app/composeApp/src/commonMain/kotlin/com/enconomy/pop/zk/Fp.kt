package com.enconomy.pop.zk

/**
 * P-256 base field, p = 2^256 - 2^224 + 2^192 + 2^96 - 1 (= the secq256r1 circuit field, the Poseidon7 field).
 *
 * An element is 8 × 32-bit limbs, little-endian, one limb per Long (high half zero), at an offset in a
 * LongArray so hash states stay flat. Inside the hashes elements are in Montgomery form (R = 2^256);
 * p ≡ -1 mod 2^32 so the Montgomery factor -p^-1 mod 2^32 is 1. Products of two limbs plus two
 * sub-2^32 addends fit 64 bits unsigned; Long wraps, so ushr/and give the unsigned halves.
 */
internal object Fp {
    const val N = 8
    const val MASK = 0xFFFFFFFFL

    val P = longArrayOf(MASK, MASK, MASK, 0L, 0L, 0L, 1L, MASK)

    /** R^2 mod p (toMont multiplier): R mod p = 2^256 - p, doubled 256 times. */
    private val R2: LongArray = run {
        val r = LongArray(N)
        // 2^256 - p = 2^224 - 2^192 - 2^96 + 1
        var borrow = 0L
        for (i in 0 until N) {
            val v = -P[i] - borrow
            r[i] = v and MASK
            borrow = if (v < 0) 1L else 0L
        }
        repeat(256) { add(r, 0, r, 0, r, 0) }
        r
    }
    private val ONE = LongArray(N).also { it[0] = 1L }

    /** a >= p (a canonical-width, 8 limbs). */
    fun geP(a: LongArray, ao: Int): Boolean {
        for (i in N - 1 downTo 0) {
            val x = a[ao + i]
            if (x != P[i]) return x > P[i]
        }
        return true
    }

    /** r = a - p (caller knows a >= p or a carried past 2^256). */
    private fun subP(r: LongArray, ro: Int, a: LongArray, ao: Int) {
        var borrow = 0L
        for (i in 0 until N) {
            val v = a[ao + i] - P[i] - borrow
            r[ro + i] = v and MASK
            borrow = (v ushr 63)
        }
    }

    /** r = a + b mod p (inputs < p). r may alias a or b. */
    fun add(r: LongArray, ro: Int, a: LongArray, ao: Int, b: LongArray, bo: Int) {
        var c = 0L
        for (i in 0 until N) {
            val v = a[ao + i] + b[bo + i] + c
            r[ro + i] = v and MASK
            c = v ushr 32
        }
        if (c != 0L || geP(r, ro)) subP(r, ro, r, ro)
    }

    /**
     * r = a·b·R^-1 mod p (CIOS). [t] is scratch of N + 2 limbs. r may alias a or b.
     * Zero limbs of p (3..5) and the unit limb (6) are folded in by hand.
     */
    fun mul(r: LongArray, ro: Int, a: LongArray, ao: Int, b: LongArray, bo: Int, t: LongArray) {
        for (i in 0 until N + 2) t[i] = 0L
        for (i in 0 until N) {
            val bi = b[bo + i]
            var c = 0L
            for (j in 0 until N) {
                val v = t[j] + a[ao + j] * bi + c
                t[j] = v and MASK
                c = v ushr 32
            }
            var v = t[N] + c
            t[N] = v and MASK
            t[N + 1] = v ushr 32
            // m = t[0]; add m·p, shift one limb down. m·MASK = (m << 32) - m.
            val m = t[0]
            val mp = m * MASK
            v = t[0] + mp
            c = v ushr 32 // low limb is zero by construction
            v = t[1] + mp + c; t[0] = v and MASK; c = v ushr 32
            v = t[2] + mp + c; t[1] = v and MASK; c = v ushr 32
            v = t[3] + c; t[2] = v and MASK; c = v ushr 32
            v = t[4] + c; t[3] = v and MASK; c = v ushr 32
            v = t[5] + c; t[4] = v and MASK; c = v ushr 32
            v = t[6] + m + c; t[5] = v and MASK; c = v ushr 32
            v = t[7] + mp + c; t[6] = v and MASK; c = v ushr 32
            v = t[N] + c; t[7] = v and MASK; c = v ushr 32
            t[N] = t[N + 1] + c
        }
        if (t[N] != 0L || geP(t, 0)) subP(r, ro, t, 0) else for (i in 0 until N) r[ro + i] = t[i]
    }

    /** acc += a·b, plain 512-bit product into a 17-limb accumulator (limbs kept < 2^32). */
    fun mulAcc(acc: LongArray, a: LongArray, ao: Int, b: LongArray, bo: Int) {
        for (i in 0 until N) {
            val ai = a[ao + i]
            var c = 0L
            for (k in 0 until N) {
                val v = acc[i + k] + ai * b[bo + k] + c
                acc[i + k] = v and MASK
                c = v ushr 32
            }
            var idx = i + N
            while (c != 0L) {
                val v = acc[idx] + c
                acc[idx] = v and MASK
                c = v ushr 32
                idx++
            }
        }
    }

    /**
     * r = acc·R^-1 mod p for acc < 2^544 (a sum of up to 16 Montgomery products). Destroys acc.
     * REDC leaves U = acc[8..16] < 2^289; fold the top limb with 2^256 ≡ K = 2^224 - 2^192 - 2^96 + 1.
     */
    fun redcWide(r: LongArray, ro: Int, acc: LongArray) {
        for (i in 0 until N) {
            val m = acc[i]
            val mp = m * MASK
            var v = acc[i] + mp
            var c = v ushr 32
            acc[i] = 0L
            v = acc[i + 1] + mp + c; acc[i + 1] = v and MASK; c = v ushr 32
            v = acc[i + 2] + mp + c; acc[i + 2] = v and MASK; c = v ushr 32
            v = acc[i + 3] + c; acc[i + 3] = v and MASK; c = v ushr 32
            v = acc[i + 4] + c; acc[i + 4] = v and MASK; c = v ushr 32
            v = acc[i + 5] + c; acc[i + 5] = v and MASK; c = v ushr 32
            v = acc[i + 6] + m + c; acc[i + 6] = v and MASK; c = v ushr 32
            v = acc[i + 7] + mp + c; acc[i + 7] = v and MASK; c = v ushr 32
            var idx = i + N
            while (c != 0L) {
                v = acc[idx] + c
                acc[idx] = v and MASK
                c = v ushr 32
                idx++
            }
        }
        var h = acc[2 * N]
        while (h != 0L) {
            // U = low + h·K; h·K limbs: [h, 0, 0, -h·2^96 ...] done as low + h·(K) with K ≥ 0 limbwise.
            acc[2 * N] = 0L
            var c = 0L
            for (k in 0 until N) {
                val v = acc[N + k] + h * K[k] + c
                acc[N + k] = v and MASK
                c = v ushr 32
            }
            h = c
        }
        if (geP(acc, N)) subP(r, ro, acc, N) else for (i in 0 until N) r[ro + i] = acc[N + i]
    }

    /** 2^256 mod p, limbs. */
    private val K = longArrayOf(1L, 0L, 0L, MASK, MASK, MASK, MASK - 1, 0L)

    /** r = a^7 (Montgomery). [s] is scratch of 2N, [t] of N + 2. r may alias a. */
    fun pow7(r: LongArray, ro: Int, a: LongArray, ao: Int, s: LongArray, t: LongArray) {
        mul(s, 0, a, ao, a, ao, t) // a^2
        mul(s, N, s, 0, s, 0, t) // a^4
        mul(s, N, s, N, s, 0, t) // a^6
        mul(r, ro, s, N, a, ao, t) // a^7
    }

    fun toMont(r: LongArray, ro: Int, a: LongArray, ao: Int, t: LongArray) = mul(r, ro, a, ao, R2, 0, t)
    fun fromMont(r: LongArray, ro: Int, a: LongArray, ao: Int, t: LongArray) = mul(r, ro, a, ao, ONE, 0, t)
}

/** A canonical field element (< p), immutable. Big-endian bytes / hex at the edges, like the spike. */
class Fe internal constructor(internal val w: LongArray) {
    init {
        require(w.size == Fp.N && !Fp.geP(w, 0)) { "not a canonical field element" }
    }

    /** 32 bytes, big-endian. */
    fun toBytes(): ByteArray {
        val b = ByteArray(32)
        for (i in 0 until Fp.N) {
            val x = w[i]
            val o = 28 - 4 * i
            b[o] = (x ushr 24).toByte(); b[o + 1] = (x ushr 16).toByte()
            b[o + 2] = (x ushr 8).toByte(); b[o + 3] = x.toByte()
        }
        return b
    }

    /** 64 lowercase hex digits, zero-padded. */
    fun toHex(): String {
        val d = "0123456789abcdef"
        val sb = StringBuilder(64)
        for (x in toBytes()) {
            val v = x.toInt() and 0xff
            sb.append(d[v ushr 4]).append(d[v and 0xf])
        }
        return sb.toString()
    }

    fun isZero(): Boolean = w.all { it == 0L }

    override fun equals(other: Any?): Boolean = other is Fe && w.contentEquals(other.w)
    override fun hashCode(): Int = w.contentHashCode()
    override fun toString(): String = "0x" + toHex()

    companion object {
        val ZERO = Fe(LongArray(Fp.N))

        /** v mod p (negative v becomes p - |v|, as the spike's fe()). */
        fun of(v: Long): Fe {
            if (v >= 0) return Fe(LongArray(Fp.N).also { it[0] = v and Fp.MASK; it[1] = v ushr 32 })
            val m = -v // |v| ≤ 2^63 fits unsigned
            val a = LongArray(Fp.N).also { it[0] = m and Fp.MASK; it[1] = m ushr 32 }
            val r = LongArray(Fp.N)
            var borrow = 0L
            for (i in 0 until Fp.N) {
                val x = Fp.P[i] - a[i] - borrow
                r[i] = x and Fp.MASK
                borrow = x ushr 63
            }
            return Fe(r)
        }

        /** 32 bytes, big-endian, must be < p. */
        fun fromBytes(b: ByteArray): Fe {
            require(b.size == 32) { "field element must be 32 bytes" }
            val w = LongArray(Fp.N)
            for (i in 0 until Fp.N) {
                val o = 28 - 4 * i
                w[i] = ((b[o].toLong() and 0xff) shl 24) or ((b[o + 1].toLong() and 0xff) shl 16) or
                    ((b[o + 2].toLong() and 0xff) shl 8) or (b[o + 3].toLong() and 0xff)
            }
            return Fe(w)
        }

        /** Hex (optional 0x, ≤ 64 digits), must be < p. */
        fun fromHex(s: String): Fe {
            val h = s.removePrefix("0x").removePrefix("0X")
            require(h.length in 1..64 && h.all { it.isDigit() || it.lowercaseChar() in 'a'..'f' }) { "bad hex" }
            val p = h.padStart(64, '0')
            val w = LongArray(Fp.N)
            for (i in 0 until Fp.N) w[Fp.N - 1 - i] = p.substring(8 * i, 8 * i + 8).toLong(16)
            return Fe(w)
        }
    }
}
