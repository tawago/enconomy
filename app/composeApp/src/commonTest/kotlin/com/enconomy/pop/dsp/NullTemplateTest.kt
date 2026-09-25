package com.enconomy.pop.dsp

import com.enconomy.pop.toHex
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.abs
import kotlin.math.sqrt
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Contract 6.2 / 6.7: null templates vs dsp_ref.null_template, rel 1e-9 (of the vector's max |x|). */
class NullTemplateTest {
    @Test fun pinnedLiterals() {
        // dsp_ref.null_template("00"*16, "A", 0, 0, 48000)[:8]
        val want = doubleArrayOf(
            -2.171744575836746e-08, 5.97041846600107e-07, 1.8355747627008143e-06, -1.903719598807515e-06,
            -5.523028857828255e-06, -1.7134374804790278e-05, -1.340421762003768e-05, 1.0695781803152786e-05,
        )
        val x = PopDsp.nullTemplate("00".repeat(16), 'A', 0, 0, 48000)
        assertEquals(12000, x.size)
        val mx = x.maxOf { abs(it) }
        for (i in want.indices) DspFixtures.assertRel(want[i], x[i], 1e-9, "x[$i]", 1e-9 * mx)
        assertEquals("1e60a08dba382b2d7e2f8d8661652fe5a1cdae9644a2ddc46df29d830758762f",
            NullCodes.seed("00".repeat(16), 'A', 0, 0).toHex())
    }

    @Test fun vectorsMatchPython() {
        val vs = DspFixtures.json("nulls.json")["vectors"]!!.jsonArray
        for ((j, e) in vs.withIndex()) {
            val v = e.jsonObject
            val sid = v["session_id_hex"]!!.jsonPrimitive.content
            val em = v["emitter"]!!.jsonPrimitive.content[0]
            val att = v["attempt"]!!.jsonPrimitive.int
            val i = v["i"]!!.jsonPrimitive.int
            val sr = v["sr"]!!.jsonPrimitive.int
            val tag = "vec$j($sid,$em,$att,$i,$sr)"
            assertEquals(v["seed_hex"]!!.jsonPrimitive.content, NullCodes.seed(sid, em, att, i).toHex(), tag)
            val x = PopDsp.nullTemplate(sid, em, att, i, sr)
            assertEquals(v["n"]!!.jsonPrimitive.int, x.size, tag)
            val mx = v["maxabs"]!!.jsonPrimitive.double
            DspFixtures.assertRel(mx, x.maxOf { abs(it) }, 1e-9, "$tag maxabs")
            val tol = 1e-9 * mx
            DspFixtures.doubles(v["first8"]).forEachIndexed { k, w -> DspFixtures.assertRel(w, x[k], 0.0, "$tag x[$k]", tol) }
            DspFixtures.doubles(v["last4"]).forEachIndexed { k, w ->
                DspFixtures.assertRel(w, x[x.size - 4 + k], 0.0, "$tag x[-${4 - k}]", tol)
            }
            val sq = sqrt(x.size.toDouble())
            DspFixtures.assertRel(v["sum"]!!.jsonPrimitive.double, x.sum(), 0.0, "$tag sum", tol * x.size)
            DspFixtures.assertRel(v["sumsq"]!!.jsonPrimitive.double, x.sumOf { it * it }, 1e-9, "$tag sumsq")
            var ws = 0.0
            for (t in x.indices) ws += x[t] * ((t % 97) - 48)
            DspFixtures.assertRel(v["wsum"]!!.jsonPrimitive.double, ws, 0.0, "$tag wsum", tol * 48 * sq * 10)
            v["full_f64_b64"]?.let { f ->
                val py = DspFixtures.f64(f.jsonPrimitive.content)
                assertEquals(py.size, x.size)
                var worst = 0.0
                for (t in x.indices) worst = maxOf(worst, abs(py[t] - x[t]))
                assertTrue(worst <= tol, "$tag full vector worst diff $worst > $tol")
            }
        }
    }

    @Test fun cacheReturnsSameFamily() {
        val a = PopDsp.nullTemplates("ab".repeat(16), 'B', 1, 48000)
        assertEquals(64, a.size)
        assertTrue(a[5].contentEquals(PopDsp.nullTemplate("ab".repeat(16), 'B', 1, 5, 48000)))
        assertTrue(a === PopDsp.nullTemplates("ab".repeat(16), 'B', 1, 48000))
    }
}
