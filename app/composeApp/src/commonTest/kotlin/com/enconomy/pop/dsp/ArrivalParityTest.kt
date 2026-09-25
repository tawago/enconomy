package com.enconomy.pop.dsp

import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** Contract 6.7: every fixture window vs dsp_ref (same int16 bytes, same float32 templates). */
class ArrivalParityTest {
    @Test fun fixturesPresent() {
        assertEquals(6, DspFixtures.fixtures.size)
        assertTrue(DspFixtures.fixtures.any { it.name == "glitch_synth" })
    }

    @Test fun scoresAndNullMaxima() {
        for (f in DspFixtures.fixtures) for (l in f.listeners.values) for (w in l.windows) {
            val tag = "${f.name} ${l.role} ${w.kind}"
            val c = assertNotNull(DspFixtures.corr(f, l, w), tag)
            assertEquals(w.expect["window_lo"]!!.jsonPrimitive.int, c.w0, "$tag w0")
            assertEquals(w.expect["window_hi"]!!.jsonPrimitive.int, c.w1, "$tag w1")
            val nm = DspFixtures.doubles(w.expect["null_maxima"])
            assertEquals(nm.size, c.nullMaxima.size)
            for (i in nm.indices) DspFixtures.assertRel(nm[i], c.nullMaxima[i], 1e-6, "$tag null_max[$i]")
            for (p in w.expect["score_probes"]!!.jsonArray) {
                val a = p.jsonArray
                val fr = a[0].jsonPrimitive.int
                DspFixtures.assertRel(a[1].jsonPrimitive.double, c.score[fr - c.w0], 1e-6, "$tag score@$fr")
            }
        }
    }

    @Test fun arrivals() {
        for (f in DspFixtures.fixtures) for (l in f.listeners.values) for (w in l.windows) {
            val tag = "${f.name} ${l.role} ${w.kind}"
            val c = assertNotNull(DspFixtures.corr(f, l, w), tag)
            val bar = PopDsp.gumbelBar(c.nullMaxima)
            val n = PopDsp.firstArrival(c.env, c.score, bar, pyRound(0.005 * l.sr))
            val found = w.expect["found"]!!.jsonPrimitive.boolean
            assertEquals(found, n >= 0, "$tag found (decision differs)")
            DspFixtures.assertRel(w.expect["bar"]!!.jsonPrimitive.double, bar, 0.01, "$tag bar")
            DspFixtures.assertRel(w.expect["null_max"]!!.jsonPrimitive.double, c.nullMaxima.max(), 1e-6, "$tag null_max")
            if (found) {
                assertEquals(w.expect["frame"]!!.jsonPrimitive.int, c.w0 + n, "$tag frame")
                DspFixtures.assertRel(w.expect["score"]!!.jsonPrimitive.double, c.score[n], 1e-6, "$tag score")
            }
            var s = 0
            for (q in c.score.indices) if (c.score[q] > c.score[s]) s = q
            assertEquals(w.expect["strongest_frame"]!!.jsonPrimitive.int, c.w0 + s, "$tag strongest")
        }
    }

    @Test fun measureArrivalMatchesPieces() {
        // the public one-call API over one window (full recompute, not the cache)
        val f = DspFixtures.fixtures.first()
        val l = f.listeners.getValue('A')
        val w = l.windows[1]
        val a = PopDsp.measureArrival(l.capture, l.sr, w.template,
            PopDsp.nullTemplates(f.sessionIdHex, w.emitter, f.attempt, l.sr), w.expected)
        assertTrue(a.found)
        assertEquals(w.expect["frame"]!!.jsonPrimitive.int, a.frame)
        assertEquals(null, a.why)
        DspFixtures.assertRel(w.expect["strongest_score"]!!.jsonPrimitive.double, a.strongestScore, 1e-6, "strongest")
    }
}
