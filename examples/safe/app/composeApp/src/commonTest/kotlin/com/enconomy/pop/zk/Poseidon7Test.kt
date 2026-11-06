package com.enconomy.pop.zk

import com.enconomy.pop.zk.ZkVectors.fe
import com.enconomy.pop.zk.ZkVectors.fes
import com.enconomy.pop.zk.ZkVectors.list
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals

/** Parity with poseidon7/p7.py (vectors from gen_vectors.py). */
class Poseidon7Test {
    private val v = ZkVectors.p7

    @Test fun permutation() {
        val cases = list(v, "perm")
        assertEquals(8, cases.size)
        for (c in cases) assertEquals(fes(c["out"]!!), Poseidon7.perm(fes(c["in"]!!)))
    }

    @Test fun spotValues() {
        // Spec §2.4, independent of the JSON.
        assertEquals(
            "b53441b5947859ddb7a6938ab257200f5432e5488686b00d025faf664b202dcb",
            Poseidon7.perm(List(5) { Fe.of(it.toLong()) })[0].toHex(),
        )
        assertEquals(
            "678179d0d4dc0eec9d951542cd484b1a1b3f846cdd7a9f939143b57ae7366039",
            Poseidon7.node5(Fe.of(1), Fe.of(2), Fe.of(3), Fe.of(4)).toHex(),
        )
        assertEquals(
            "892b94c43e27b362a254ccbfe2480510cc7a2930e0dc8ea82d69f4b8e1e94714",
            Poseidon7.hash16(Poseidon7.TAG_HOLD, listOf(Fe.of(1))).toHex(),
        )
        assertEquals(
            "155a502f4baf3a57d8dc33a6874c793fa4c546e7596caaa47ac6be54ed6c98ff",
            Poseidon7.hash16(Poseidon7.TAG_HALF2, List(9) { Fe.of(it + 1L) }).toHex(),
        )
    }

    @Test fun node5() {
        for (c in list(v, "node5")) {
            val x = fes(c["in"]!!)
            assertEquals(fe(c["out"]!!), Poseidon7.node5(x[0], x[1], x[2], x[3]))
        }
    }

    @Test fun sponge16() {
        val cases = list(v, "sponge16")
        assertEquals(7, cases.size)
        for (c in cases) {
            val out = fes(c["out"]!!)
            val tag = c["tag"]!!.jsonPrimitive.int.toLong()
            assertEquals(out, Poseidon7.sponge16(tag, fes(c["in"]!!), out.size))
        }
    }
}
