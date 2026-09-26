package com.enconomy.pop.zk

/**
 * Poseidon, S-box x^7, over the P-256 base field: the optionA-v2 spike's poseidon7/p7.py, bit for bit.
 *
 * perm      per round r: state += C[r·t .. r·t+t-1]; x^7 on every cell (first and last R_F/2 rounds)
 *           or on cell 0 only (the R_P middle rounds); state = M · state
 * sponge16  t = 16, cell 0 = domain tag (set), absorb 15 per block by adding into cells 1..15, permute
 *           after each block (last block zero-padded, at least one block); outputs cells 1, 2, ...
 * node5     t = 5: perm([TAG_NODE, c0, c1, c2, c3])[1]
 */
object Poseidon7 {
    const val TAG_LEAF = 1L + (1024L shl 8)
    const val TAG_NODE = 2L
    const val TAG_NULL = 5L
    const val TAG_HOLD = 6L
    const val TAG_HALF2 = 8L

    /** Round constants and MDS as generated (hex, see Poseidon7Params). */
    class Params internal constructor(
        val t: Int,
        val rf: Int,
        val rp: Int,
        private val c: Array<String>,
        private val m: Array<String>,
    ) {
        /** C, flat, Montgomery: cell (r, i) at ((r·t + i)·N). */
        internal val cMont: LongArray by lazy { parse(c, rf + rp) }

        /** M, flat, Montgomery: entry (i, j) at ((i·t + j)·N). */
        internal val mMont: LongArray by lazy { parse(m, t) }

        private fun parse(rows: Array<String>, nRows: Int): LongArray {
            require(rows.size == nRows && rows.all { it.length == 64 * t })
            val out = LongArray(nRows * t * Fp.N)
            val scratch = LongArray(Fp.N + 2)
            for ((r, row) in rows.withIndex()) for (i in 0 until t) {
                val o = (r * t + i) * Fp.N
                val fe = Fe.fromHex(row.substring(64 * i, 64 * i + 64))
                Fp.toMont(out, o, fe.w, 0, scratch)
            }
            return out
        }
    }

    internal fun params(t: Int): Params = when (t) {
        5 -> Poseidon7Params.T5
        16 -> Poseidon7Params.T16
        else -> throw IllegalArgumentException("no Poseidon7 params for t=$t")
    }

    fun perm(state: List<Fe>): List<Fe> {
        val w = Perm(params(state.size))
        for ((i, x) in state.withIndex()) w.setCell(i, x)
        w.permute()
        return List(state.size) { w.cell(it) }
    }

    /** sponge16(tag, xs) outputs cells 1 .. nout. */
    fun sponge16(tag: Long, xs: List<Fe>, nout: Int = 1): List<Fe> {
        require(nout in 1..15)
        val w = Perm(params(16))
        val src = LongArray(xs.size * Fp.N)
        for ((k, x) in xs.withIndex()) x.w.copyInto(src, k * Fp.N)
        w.absorb(tag, xs.size, src)
        return List(nout) { w.cell(1 + it) }
    }

    fun hash16(tag: Long, xs: List<Fe>): Fe = sponge16(tag, xs, 1)[0]

    fun node5(c0: Fe, c1: Fe, c2: Fe, c3: Fe): Fe =
        Perm(params(5)).node(c0.w, 0, c1.w, 0, c2.w, 0, c3.w, 0).cell(1)

    /** One permutation's working state; not thread-safe, reuse within one thread. */
    internal class Perm(val p: Params) {
        private val t = p.t.also { require(it <= 16) }
        val st = LongArray(t * Fp.N)
        private val nx = LongArray(t * Fp.N)
        private val prod = LongArray(Fp.N)
        private val sq = LongArray(2 * Fp.N)
        private val acc = LongArray(2 * Fp.N + 2)
        val scratch = LongArray(Fp.N + 2)

        fun setCell(i: Int, x: Fe) = Fp.toMont(st, i * Fp.N, x.w, 0, scratch)

        fun cell(i: Int): Fe = LongArray(Fp.N).also { Fp.fromMont(it, 0, st, i * Fp.N, scratch) }.let(::Fe)

        fun permute() {
            val n = Fp.N
            val c = p.cMont
            val m = p.mMont
            val half = p.rf / 2
            var s = st
            var d = nx
            for (r in 0 until p.rf + p.rp) {
                for (i in 0 until t) Fp.add(s, i * n, s, i * n, c, (r * t + i) * n)
                if (r < half || r >= half + p.rp) {
                    for (i in 0 until t) Fp.pow7(s, i * n, s, i * n, sq, scratch)
                } else {
                    Fp.pow7(s, 0, s, 0, sq, scratch)
                }
                // Row sums of plain products, one reduction per row (t ≤ 16: sum < 16 p^2 < 2^516).
                for (i in 0 until t) {
                    acc.fill(0L)
                    for (j in 0 until t) Fp.mulAcc(acc, m, (i * t + j) * n, s, j * n)
                    Fp.redcWide(d, i * n, acc)
                }
                val tmp = s; s = d; d = tmp
            }
            if (s !== st) s.copyInto(st)
        }

        /**
         * sponge16 absorb of [count] canonical inputs (input k's limbs at src[k·N]),
         * starting from [tag, 0, ...]. Leaves the result in st (Montgomery).
         */
        fun absorb(tag: Long, count: Int, src: LongArray) {
            check(t == 16)
            st.fill(0L)
            Fp.toMont(st, 0, Fe.of(tag).w, 0, scratch)
            val nb = maxOf(1, (count + 14) / 15)
            for (b in 0 until nb) {
                for (i in 0 until 15) {
                    val k = 15 * b + i
                    if (k >= count) break
                    Fp.toMont(prod, 0, src, k * Fp.N, scratch)
                    Fp.add(st, (1 + i) * Fp.N, st, (1 + i) * Fp.N, prod, 0)
                }
                permute()
            }
        }

        /** node5 on canonical children; result cell 1 (Montgomery in st). */
        fun node(a: LongArray, ao: Int, b: LongArray, bo: Int, c: LongArray, co: Int, d: LongArray, dO: Int): Perm {
            check(t == 5)
            Fp.toMont(st, 0, Fe.of(TAG_NODE).w, 0, scratch)
            Fp.toMont(st, Fp.N, a, ao, scratch)
            Fp.toMont(st, 2 * Fp.N, b, bo, scratch)
            Fp.toMont(st, 3 * Fp.N, c, co, scratch)
            Fp.toMont(st, 4 * Fp.N, d, dO, scratch)
            permute()
            return this
        }
    }
}
