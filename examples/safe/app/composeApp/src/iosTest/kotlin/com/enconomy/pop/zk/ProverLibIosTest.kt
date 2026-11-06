package com.enconomy.pop.zk

import com.enconomy.pop.readComposeResource
import com.enconomy.pop.testEnv
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import kotlin.time.Duration.Companion.minutes

/**
 * libpop_prover.a linked through cinterop. The prove test is heavy (~2 GB, a minute on the simulator)
 * and runs only with POP_ZK_KEYS=<dir holding oa2t_s48.pk.zst> in the gradle environment.
 */
class ProverLibIosTest {
    @Test
    fun linkedAndReportsErrors() {
        assertTrue(ProverLib.available, ProverLib.loadError ?: "")
        assertTrue(ProverLib.version().isNotEmpty())
        val e = assertFailsWith<ProverException> { ProverLib.open("/nonexistent/oa2t_s48.pk.zst") }
        assertEquals("Io", e.code)
        assertEquals(0, ProverLib.sampleRate(0))
    }

    @Test
    fun provesBenchFixture() = runTest(timeout = 10.minutes) {
        val keys = testEnv("POP_ZK_KEYS") ?: return@runTest
        val fx = BenchFixture.parse(readComposeResource("files/zk/bench_180ca04b_48k_A.json"))
        val cache = KeyCache(keys, { _, _, _, _ -> error("no download in tests") })
        val out = ProofRunner(cache).run(fx.source, allowDownload = false, onStatus = {}, force = true, expectPublicSha = fx.publicSha)
        assertNotNull(out)
        assertTrue(out.stats.publicMatches)
        assertEquals(fx.halfCommit, out.stats.halfCommit)
        assertTrue(out.proof.size in 1_500_000..1_800_000, "proof ${out.proof.size}")
        println("prover bench (simulator): " + out.stats.lines().joinToString(" | "))
    }
}
