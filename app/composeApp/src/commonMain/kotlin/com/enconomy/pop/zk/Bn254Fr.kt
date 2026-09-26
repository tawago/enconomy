package com.enconomy.pop.zk

/**
 * BN254 scalar field (the Noir / barretenberg `Field`),
 * r = 21888242871839275222246405745257275088548364400416034343698204186575808495617.
 *
 * Same layout as the P-256 [Fp]: 8 x 32-bit limbs, little-endian, one limb per Long, at an offset in a
 * LongArray. Hash internals keep elements in Montgomery form (R = 2^256). Unlike P-256 the modulus has no
 * special shape, so the CIOS loop uses the full -r^-1 mod 2^32.
 */
internal object Bn254 {
    const val N = 8
    const val MASK = 0xFFFFFFFFL

    /** r, little-endian 32-bit limbs. */
    val P: LongArray = limbsFromHex("30644e72e131a029b85045b68181585d2833e84879b9709143e1f593f0000001")

    /** -r^-1 mod 2^32. */
    private val NINV: Long = run {
        var inv = 1L
        repeat(6) { inv = (inv * (2L - P[0] * inv)) and MASK }
        (-inv) and MASK
    }

    /** R^2 mod r: 1 doubled 512 times. */
    private val R2: LongArray = run {
        val x = LongArray(N).also { it[0] = 1L }
        repeat(512) { add(x, 0, x, 0, x, 0) }
        x
    }
    private val ONE_RAW = LongArray(N).also { it[0] = 1L }

    fun limbsFromHex(h: String): LongArray {
        val s = h.removePrefix("0x").removePrefix("0X").padStart(64, '0')
        require(s.length == 64) { "hex too long" }
        val out = LongArray(N)
        for (i in 0 until N) out[i] = s.substring(64 - 8 * (i + 1), 64 - 8 * i).toLong(16)
        return out
    }

    fun geP(a: LongArray, ao: Int): Boolean {
        for (i in N - 1 downTo 0) {
            val x = a[ao + i]
            if (x != P[i]) return x > P[i]
        }
        return true
    }

    private fun subP(r: LongArray, ro: Int, a: LongArray, ao: Int) {
        var borrow = 0L
        for (i in 0 until N) {
            val v = a[ao + i] - P[i] - borrow
            r[ro + i] = v and MASK
            borrow = v ushr 63
        }
    }

    /** r = a + b mod p (inputs < p). May alias. */
    fun add(r: LongArray, ro: Int, a: LongArray, ao: Int, b: LongArray, bo: Int) {
        var c = 0L
        for (i in 0 until N) {
            val v = a[ao + i] + b[bo + i] + c
            r[ro + i] = v and MASK
            c = v ushr 32
        }
        if (c != 0L || geP(r, ro)) subP(r, ro, r, ro)
    }

    /** r = a - b mod p (inputs < p). May alias. */
    fun sub(r: LongArray, ro: Int, a: LongArray, ao: Int, b: LongArray, bo: Int) {
        var borrow = 0L
        for (i in 0 until N) {
            val v = a[ao + i] - b[bo + i] - borrow
            r[ro + i] = v and MASK
            borrow = v ushr 63
        }
        if (borrow != 0L) {
            var c = 0L
            for (i in 0 until N) {
                val v = r[ro + i] + P[i] + c
                r[ro + i] = v and MASK
                c = v ushr 32
            }
        }
    }

    /** r = a·b·R^-1 mod p (CIOS). [t] is scratch of N + 2 limbs. r may alias a or b. */
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
            val m = (t[0] * NINV) and MASK
            v = t[0] + m * P[0]
            c = v ushr 32
            for (j in 1 until N) {
                v = t[j] + m * P[j] + c
                t[j - 1] = v and MASK
                c = v ushr 32
            }
            v = t[N] + c
            t[N - 1] = v and MASK
            t[N] = t[N + 1] + (v ushr 32)
        }
        if (t[N] != 0L || geP(t, 0)) subP(r, ro, t, 0) else for (i in 0 until N) r[ro + i] = t[i]
    }

    /** canonical (< p) limbs -> Montgomery, in place. */
    fun toMont(a: LongArray, ao: Int, t: LongArray) = mul(a, ao, a, ao, R2, 0, t)

    /** Montgomery -> canonical, in place. */
    fun fromMont(a: LongArray, ao: Int, t: LongArray) = mul(a, ao, a, ao, ONE_RAW, 0, t)
}

/** Immutable BN254 field element (Montgomery limbs inside). */
class Fr internal constructor(internal val m: LongArray) {
    operator fun plus(o: Fr): Fr = Fr(LongArray(Bn254.N)).also { Bn254.add(it.m, 0, m, 0, o.m, 0) }
    operator fun minus(o: Fr): Fr = Fr(LongArray(Bn254.N)).also { Bn254.sub(it.m, 0, m, 0, o.m, 0) }
    operator fun times(o: Fr): Fr = Fr(LongArray(Bn254.N)).also { Bn254.mul(it.m, 0, m, 0, o.m, 0, LongArray(Bn254.N + 2)) }
    operator fun unaryMinus(): Fr = ZERO - this

    /** canonical little-endian 32-bit limbs. */
    internal fun canonical(): LongArray = m.copyOf().also { Bn254.fromMont(it, 0, LongArray(Bn254.N + 2)) }

    /** 32 bytes, big-endian, canonical. */
    fun toBytes(): ByteArray {
        val c = canonical()
        val out = ByteArray(32)
        for (i in 0 until Bn254.N) {
            val v = c[i]
            val o = 32 - 4 * (i + 1)
            out[o] = (v ushr 24).toByte(); out[o + 1] = (v ushr 16).toByte()
            out[o + 2] = (v ushr 8).toByte(); out[o + 3] = v.toByte()
        }
        return out
    }

    /** "0x" + 64 lowercase hex digits (same as Noir / Python output). */
    fun toHex(): String = "0x" + toBytes().joinToString("") { (it.toInt() and 0xFF).toString(16).padStart(2, '0') }

    override fun equals(other: Any?): Boolean = other is Fr && m.contentEquals(other.m)
    override fun hashCode(): Int = m.contentHashCode()
    override fun toString(): String = toHex()

    companion object {
        val ZERO = Fr(LongArray(Bn254.N))
        val ONE = of(1)

        /** from canonical little-endian limbs (< p, caller guarantees). */
        internal fun fromCanonical(c: LongArray): Fr =
            Fr(c.copyOf()).also { Bn254.toMont(it.m, 0, LongArray(Bn254.N + 2)) }

        /** signed Long, reduced mod p (negative -> p - |v|). */
        fun of(v: Long): Fr {
            if (v < 0) return ZERO - of(-v) // -Long.MIN_VALUE not supported
            val c = LongArray(Bn254.N)
            c[0] = v and Bn254.MASK
            c[1] = v ushr 32
            return fromCanonical(c)
        }

        /** big-endian hex, must be < p. */
        fun fromHex(h: String): Fr {
            val c = Bn254.limbsFromHex(h)
            require(!Bn254.geP(c, 0)) { "not canonical: $h" }
            return fromCanonical(c)
        }

        /** big-endian bytes of any length, reduced mod p (Horner, byte by byte). */
        fun fromBytesReduce(b: ByteArray): Fr {
            val k256 = of(256)
            var acc = ZERO
            for (x in b) acc = acc * k256 + of((x.toInt() and 0xFF).toLong())
            return acc
        }

        /** big-endian bytes, at most 31 (always < p), no reduction needed. */
        fun fromBytesSmall(b: ByteArray, off: Int = 0, len: Int = b.size): Fr {
            require(len <= 31)
            val c = LongArray(Bn254.N)
            for (i in 0 until len) {
                val bit = 8 * (len - 1 - i)
                c[bit / 32] = c[bit / 32] or ((b[off + i].toLong() and 0xFF) shl (bit % 32))
            }
            return fromCanonical(c)
        }

        /** decimal string (Prover.toml style), reduced mod p. */
        fun fromDecimal(s: String): Fr {
            val t = s.trim()
            if (t.startsWith("-")) return -fromDecimal(t.substring(1))
            if (t.startsWith("0x") || t.startsWith("0X")) return fromHex(t)
            val ten = of(10)
            var acc = ZERO
            for (ch in t) acc = acc * ten + of((ch - '0').toLong())
            return acc
        }
    }
}
