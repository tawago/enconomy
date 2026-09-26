package com.enconomy.pop.zk

/**
 * circomlib Poseidon(n) over BN254 Fr, n = 1..3 (t = 2..4), x^5, RF = 8, RP = 56/57/56.
 * Matches circomlib poseidon.circom, circomlibjs, poseidon-lite, poseidon-solidity PoseidonT2..T4.
 * Inputs are reduced mod r (same as circom witness gen and poseidon-solidity).
 */
object PoseidonBn254 {
    val R = BigNat.fromHex("30644e72e131a029b85045b68181585d2833e84879b9709143e1f593f0000001")
    private class K(val rp: Int, val c: List<BigNat>, val m: List<List<BigNat>>)
    private val ks: Map<Int, K> by lazy {
        with(PoseidonBn254Params) {
            mapOf(2 to K(56, C2.map(BigNat::fromHex), M2.map { r -> r.map(BigNat::fromHex) }),
                  3 to K(57, C3.map(BigNat::fromHex), M3.map { r -> r.map(BigNat::fromHex) }),
                  4 to K(56, C4.map(BigNat::fromHex), M4.map { r -> r.map(BigNat::fromHex) }))
        }
    }
    private fun pow5(x: BigNat): BigNat { val x2 = (x * x) % R; return (((x2 * x2) % R) * x) % R }

    fun hash(inputs: List<BigNat>): BigNat {
        val t = inputs.size + 1
        val k = ks[t] ?: throw IllegalArgumentException("PoseidonBn254: 1..3 inputs, got ${inputs.size}")
        var s = MutableList(t) { i -> if (i == 0) BigNat.ZERO else inputs[i - 1] % R }
        for (r in 0 until 8 + k.rp) {
            val full = r < 4 || r >= 4 + k.rp
            for (i in 0 until t) {
                val a = (s[i] + k.c[r * t + i]) % R
                s[i] = if (full || i == 0) pow5(a) else a
            }
            s = MutableList(t) { i -> var acc = BigNat.ZERO; for (j in 0 until t) acc += k.m[i][j] * s[j]; acc % R }
        }
        return s[0]
    }
}
