package com.enconomy.pop.zk

import com.enconomy.pop.TranscriptCodec
import com.enconomy.pop.readComposeResource
import com.enconomy.pop.sha256
import com.enconomy.pop.testEnv
import com.enconomy.pop.toHex
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * Witness input parity with the spike's prep_popt2.py on the bundled bench fixtures (tools/gen_bench.py):
 * every field's compact JSON, halfCommit, and the public vector the verifier derives.
 * POP_ZK_DUMP=<dir> also writes the inputs there (host check: `popprover check <pk> <input>`).
 */
class WitnessInputTest {
    private fun fixture(n: String) = BenchFixture.parse(readComposeResource("files/zk/bench_$n.json"))

    @Test
    fun matchesSpikeInputs() {
        for (n in BenchFixture.NAMES) {
            val fx = fixture(n)
            val b = WitnessInput.build(fx.source)
            assertEquals(emptyList(), fx.fieldMismatches(b), n)
            assertEquals(fx.halfCommit, b.halfCommit.toDecimal(), n)
            assertEquals(fx.publicSha, sha256(ProofRunner.publicJson(b.expectedPublic).encodeToByteArray()).toHex(), n)
            assertEquals(if (n.contains("mix")) 44111 else 48011, b.expectedPublic.size)
            testEnv("POP_ZK_DUMP")?.let { ZkFiles.write("$it/$n.input.json", b.json.encodeToByteArray()) }
        }
    }

    @Test
    fun refusesWhatTheCircuitWouldReject() {
        val fx = fixture("180ca04b_48k_A")
        val s = fx.source
        fun with(tx: ByteArray = s.transcript, validAt: Long = s.validAt, capture: ShortArray = s.capture) =
            ProofSource(tx, s.sig, capture, s.own, s.partner, s.cred, s.credSig, s.issuerPub, validAt, s.salt)

        // expired credential
        assertEquals("credential_expired", assertFailsWith<UnprovableException> { WitnessInput.build(with(validAt = s.cred.expiry + 1)) }.reason)
        // one sample changed: rec_root no longer matches
        val x = s.capture.copyOf().also { it[50_000] = (it[50_000] + 1).toShort() }
        assertEquals("rec_root", assertFailsWith<UnprovableException> { WitnessInput.build(with(capture = x)) }.reason)
        // a_self moved (re-encoded, so only the rule catches it)
        val t = TranscriptCodec.decodeTranscript2(s.transcript)
        val late = TranscriptCodec.transcript2(t.copy(aSelf = t.aSelf + 1, selfOsDelta = t.selfOsDelta + 1, half = t.half - 1))
        assertEquals("self_rule", assertFailsWith<UnprovableException> { WitnessInput.build(with(tx = late)) }.reason)
        // |self_os_delta| > delta
        val far = TranscriptCodec.transcript2(t.copy(selfOsDelta = t.selfOsDelta + 200))
        assertEquals("self_os_delta", assertFailsWith<UnprovableException> { WitnessInput.build(with(tx = far)) }.reason)
    }

    @Test
    fun bigNat() {
        assertEquals("115792089210356248762697446949407573530086143415290314195533631308867097853951", BigNat.P.toDecimal())
        val s = BigNat.fromHex("ea4524dbb63b7f3fc1bc16ab76bed158f04a85f13d654f09d995af181e085f09")
        val inv = s.modInversePrime(BigNat.N)
        assertEquals(BigNat.ONE, (s * inv) % BigNat.N)
        assertEquals("0", BigNat.ZERO.toDecimal())
        assertEquals("4294967296", BigNat.of(1L shl 32).toDecimal())
        assertTrue(BigNat.fromBytes(ByteArray(32) { 0xff.toByte() }) > BigNat.P)
    }
}
