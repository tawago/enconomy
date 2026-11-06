package com.enconomy.pop.dsp

import com.enconomy.pop.ArmReq
import com.enconomy.pop.PopConstants
import com.enconomy.pop.Popt2Config
import com.enconomy.pop.popJson
import com.enconomy.pop.readTestResource
import com.enconomy.pop.readTestResourceBytes
import com.enconomy.pop.zk.ZkVectors
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Popt2RuleTest {
    private val r48 = Popt2Rates.builtIn[48000]!!

    @Test fun passesIsExact() {
        // 25·4 vs 10·10: tie passes (≥), one more fails
        assertTrue(Popt2Rule.passes(3, 4, 10, 10, 4))
        assertFalse(Popt2Rule.passes(3, -4, 11, 10, 4))
        // beyond 64 bits: I² = 2^80 = 2^62 · 2^18
        val i = 1L shl 40
        assertTrue(Popt2Rule.passes(-i, 0, 1L shl 62, 1L shl 18, 1))
        assertFalse(Popt2Rule.passes(i, 0, (1L shl 62) + 1, 1L shl 18, 1))
        // |I|, |Q| at the rule's bound (< 2^36) with B near 2^23 and E·cn2 near 2^90
        val big = (1L shl 36) - 1
        val e = Long.MAX_VALUE / 2
        val lhs = (big.toDouble() * big * 2) * 4474747
        val cn2 = (lhs / e).toLong()
        assertTrue(Popt2Rule.passes(big, big, e, cn2 - 1, 4474747))
        assertFalse(Popt2Rule.passes(big, big, e, cn2 + 1, 4474747))
        assertTrue(Popt2Rule.passes(0, 0, 0, 12345, 1)) // digital zeros pass, as in the circuit
    }

    @Test fun ratesMatchServerConfig() {
        val cfg = popJson.parseToJsonElement(readTestResource("zk/server_config_v2.json")).jsonObject
        assertEquals(emptyList(), PopConstants.mismatches(cfg))
        val c = assertNotNull(Popt2Config.from(cfg))
        assertEquals(setOf(44100, 48000), c.rates.keys)
        assertEquals(PopConstants.SELF_OS_TOL_MS, c.selfOsTolMs)
        for ((sr, r) in c.rates) assertTrue(r.sameAs(Popt2Rates.builtIn[sr]!!))
        assertEquals(96, c.rate(48000)!!.delta)
        assertNull(c.rate(96000))
        // a v1 server, or different v2 numbers: no v2
        assertNull(Popt2Config.from(JsonObject(cfg - "popt2_rates")))
        assertNull(Popt2Config.from(JsonObject(cfg + ("popt_versions" to JsonArray(listOf(JsonPrimitive(1)))))))
        assertNull(Popt2Config.from(JsonObject(cfg + ("delta_ms" to JsonPrimitive(3)))))
        val bent = cfg["popt2_rates"]!!.jsonObject.let { t ->
            JsonObject(t + ("48000" to JsonObject(t["48000"]!!.jsonObject + ("B" to JsonPrimitive(4474748)))))
        }
        assertEquals(setOf(44100), Popt2Config.from(JsonObject(cfg + ("popt2_rates" to bent)))!!.rates.keys)
    }

    @Test fun armBodyV1Unchanged() {
        assertEquals("""{"attempt":0,"sample_rate":48000,"rtt_min_ms":12.5}""", popJson.encodeToString(ArmReq.serializer(), ArmReq(0, 48000, 12.5)))
        assertEquals("""{"attempt":1,"sample_rate":44100,"rtt_min_ms":3.0,"popt":2}""",
            popJson.encodeToString(ArmReq.serializer(), ArmReq(1, 44100, 3.0, popt = 2)))
    }

    /** One real code (2dc2eb59, emitter A at 48 kHz) for synthetic captures. */
    private val codeA: Popt2Code by lazy {
        val o = ZkVectors.json("popt2/2dc2eb59.json")
        val bin = readTestResourceBytes("zk/popt2/2dc2eb59.bin")
        val c = o["codes"]!!.jsonObject["48000"]!!.jsonObject["A"]!!.jsonObject
        fun blob(k: String) = c[k]!!.jsonObject.let { b ->
            val off = b["off"]!!.jsonPrimitive.int
            bin.copyOfRange(off, off + b["len"]!!.jsonPrimitive.int)
        }
        Popt2Code(blob("cI"), blob("cQ"))
    }

    /** 2.5 s at 48 kHz: noise, plus the code's cI (×[gain]) at [at]. */
    private fun capture(at: Int?, gain: Int = 60, noise: Int = 200, seed: Int = 1): ShortArray {
        val rnd = Random(seed)
        val x = IntArray(120000) { rnd.nextInt(-noise, noise + 1) }
        if (at != null) for (n in 0 until codeA.n) if (at + n < x.size) x[at + n] += gain * codeA.cI[n]
        return ShortArray(x.size) { x[it].coerceIn(-32768, 32767).toShort() }
    }

    @Test fun screenEqualsExact() {
        val x = capture(30000)
        for ((lo, hi) in listOf(29000 to 31000, 29990 to 30010, 40000 to 40400)) {
            val a = Popt2Rule.earliest(x, codeA, lo, hi, r48)
            val b = Popt2Rule.earliest(x, codeA, lo, hi, r48, screen = false)
            assertEquals(b, a, "[$lo, $hi)")
        }
        assertEquals(null, Popt2Rule.earliest(x, codeA, 40000, 40400, r48).frame)
        // the rising edge crosses 9 % before the true onset: earliest, not the peak
        val a = Popt2Rule.earliest(x, codeA, 29000, 31000, r48).frame!!
        assertTrue(a in 29900..30005, "$a")
    }

    @Test fun roundSteps() {
        val sr = 48000
        val own = codeA
        // self at 30000, p_self 30010 → sod −10 (ok); partner = same code at 75000
        val x = capture(30000).also { y ->
            val z = capture(75000, seed = 2)
            for (i in 70000 until 90000) y[i] = z[i]
        }
        val r = PopRound2(x, r48, 'B')
        val s = r.selfCheck(own, 30010.4)
        assertIs<PopRound2.Step.SelfOk>(s)
        assertEquals(30010, s.pSelf)
        assertEquals(s.aSelf - 30010, s.selfOsDelta)
        val p = r.measurePartner(own, 74990.0)
        assertIs<PopRound2.Step.PartnerOk>(p)
        assertEquals(s.aSelf - p.aPartner, p.half) // B: t_BB − t_AB
        assertEquals(r.provable, kotlin.math.abs(s.selfOsDelta) <= 96)

        // self sound 60 ms off the OS timestamp: over SELF_OS_TOL_MS (50)
        val late = PopRound2(capture(30000 + 60 * sr / 1000 + 200), r48, 'A').selfCheck(own, 30000.0)
        assertIs<PopRound2.Step.Failed>(late)
        assertEquals(DspReason.SELF_TIMESTAMP_MISMATCH, late.reason)
        // the same phone calibrated at 60 ms: |sod − cal| ≈ 4 ms, passes; at 10 ms it is still 54 ms off
        val calOk = PopRound2(capture(30000 + 60 * sr / 1000 + 200), r48, 'A', calUs = 60_000).selfCheck(own, 30000.0)
        assertIs<PopRound2.Step.SelfOk>(calOk)
        // cal is folded into p_self: the signed self_os_delta is the residual (200 frames), not 60 ms + 200
        assertEquals(30000 + 60 * sr / 1000, calOk.pSelf)
        assertTrue(kotlin.math.abs(calOk.selfOsDelta - 200) <= 16, "residual ${calOk.selfOsDelta}")
        assertEquals(DspReason.SELF_TIMESTAMP_MISMATCH,
            (PopRound2(capture(30000 + 60 * sr / 1000 + 200), r48, 'A', calUs = 10_000).selfCheck(own, 30000.0) as PopRound2.Step.Failed).reason)
        // a tighter shared tolerance moves the bar
        assertEquals(DspReason.SELF_TIMESTAMP_MISMATCH,
            (PopRound2(capture(30000), r48, 'A', selfOsTolMs = 0).selfCheck(own, 30500.0) as PopRound2.Step.Failed).reason)
        // nothing played
        assertEquals(DspReason.SELF_NOT_HEARD, (PopRound2(capture(null), r48, 'A').selfCheck(own, 30000.0) as PopRound2.Step.Failed).reason)
        // 20 ms dropped block in the window
        val g = capture(30000).also { it.fill(0, 31000, 31960) }
        assertEquals(DspReason.GLITCH, (PopRound2(g, r48, 'A').selfCheck(own, 30000.0) as PopRound2.Step.Failed).reason)
        // wrong length / wrong code length
        assertEquals(DspReason.CAPTURE_FAILED, (PopRound2(ShortArray(1000), r48, 'A').selfCheck(own, 300.0) as PopRound2.Step.Failed).reason)
    }
}
