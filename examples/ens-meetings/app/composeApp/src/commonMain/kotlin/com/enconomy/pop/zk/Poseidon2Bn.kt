package com.enconomy.pop.zk

/**
 * barretenberg poseidon2_permutation (Noir std::hash::poseidon2_permutation), BN254, t = 4.
 * Initial external M4, 4 full rounds, 56 partial rounds (state[0] only), 4 full rounds; x^5 S-box.
 * State: 4 Montgomery elements in a flat LongArray(32). Not thread-safe per instance (scratch buffers).
 */
class Poseidon2Bn {
    private val t = LongArray(Bn254.N + 2)
    private val x2 = LongArray(Bn254.N)
    private val x4 = LongArray(Bn254.N)
    private val tmp = LongArray(6 * Bn254.N)

    private fun sbox(s: LongArray, o: Int) {
        Bn254.mul(x2, 0, s, o, s, o, t)
        Bn254.mul(x4, 0, x2, 0, x2, 0, t)
        Bn254.mul(s, o, x4, 0, s, o, t)
    }

    /** M4 = [[5,7,1,3],[4,6,1,1],[1,3,5,7],[1,1,4,6]], in place. */
    private fun ext(s: LongArray) {
        val n = Bn254.N
        val a = 0; val b = n; val c = 2 * n; val d = 3 * n
        val t0 = 0; val t1 = n; val t2 = 2 * n; val t3 = 3 * n; val t4 = 4 * n; val t5 = 5 * n
        val w = tmp
        Bn254.add(w, t0, s, a, s, b)
        Bn254.add(w, t1, s, c, s, d)
        Bn254.add(w, t2, s, b, s, b); Bn254.add(w, t2, w, t2, w, t1)
        Bn254.add(w, t3, s, d, s, d); Bn254.add(w, t3, w, t3, w, t0)
        Bn254.add(w, t4, w, t1, w, t1); Bn254.add(w, t4, w, t4, w, t4); Bn254.add(w, t4, w, t4, w, t3)
        Bn254.add(w, t5, w, t0, w, t0); Bn254.add(w, t5, w, t5, w, t5); Bn254.add(w, t5, w, t5, w, t2)
        Bn254.add(s, a, w, t3, w, t5)
        for (i in 0 until n) s[b + i] = w[t5 + i]
        Bn254.add(s, c, w, t2, w, t4)
        for (i in 0 until n) s[d + i] = w[t4 + i]
    }

    private fun full(s: LongArray, r: Int) {
        for (k in 0 until 4) {
            Bn254.add(s, k * Bn254.N, s, k * Bn254.N, EXT, (4 * r + k) * Bn254.N)
            sbox(s, k * Bn254.N)
        }
        ext(s)
    }

    /** permute 4 Montgomery elements in place. */
    fun permute(s: LongArray) {
        val n = Bn254.N
        ext(s)
        for (r in 0 until 4) full(s, r)
        val sum = tmp
        for (i in 0 until NPARTIAL) {
            Bn254.add(s, 0, s, 0, INT, i * n)
            sbox(s, 0)
            Bn254.add(sum, 0, s, 0, s, n)
            Bn254.add(sum, 0, sum, 0, s, 2 * n)
            Bn254.add(sum, 0, sum, 0, s, 3 * n)
            for (k in 0 until 4) {
                Bn254.mul(s, k * n, s, k * n, DIAG, k * n, t)
                Bn254.add(s, k * n, s, k * n, sum, 0)
            }
        }
        for (r in 4 until 8) full(s, r)
    }

    /** convenience: permute 4 elements. */
    fun permute(x: List<Fr>): List<Fr> {
        require(x.size == 4)
        val s = LongArray(4 * Bn254.N)
        for (k in 0 until 4) x[k].m.copyInto(s, k * Bn254.N)
        permute(s)
        return List(4) { k -> Fr(s.copyOfRange(k * Bn254.N, (k + 1) * Bn254.N)) }
    }

    companion object {
        const val NPARTIAL = 56
        private fun mont(hs: Array<String>): LongArray {
            val out = LongArray(hs.size * Bn254.N)
            hs.forEachIndexed { i, h -> Fr.fromHex(h).m.copyInto(out, i * Bn254.N) }
            return out
        }
        internal val DIAG = mont(Poseidon2BnParams.DIAG)
        internal val EXT = mont(Poseidon2BnParams.EXT)
        internal val INT = mont(Poseidon2BnParams.INT)
    }
}
