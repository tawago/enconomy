package com.enconomy.pop.dsp

import com.enconomy.pop.PopConstants
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

/** Contract 6.4: bar within 1% of scipy gumbel_r.fit/isf (dsp_ref.gumbel_bar). */
class GumbelTest {
    @Test fun pinnedSample() {
        val g = DspFixtures.json("nulls.json")["gumbel"]!!.jsonArray[0].jsonObject
        val s = DspFixtures.doubles(g["maxima"])
        val fit = assertNotNull(Gumbel.fit(s))
        val py = DspFixtures.doubles(g["fit"])
        DspFixtures.assertRel(py[0], fit.loc, 1e-6, "loc")
        DspFixtures.assertRel(py[1], fit.scale, 1e-5, "scale")
        DspFixtures.assertRel(g["bar"]!!.jsonPrimitive.double, PopDsp.gumbelBar(s), 0.01, "bar")
    }

    @Test fun everyFixtureWindow() {
        for (f in DspFixtures.fixtures) for (l in f.listeners.values) for (w in l.windows) {
            val s = DspFixtures.doubles(w.expect["null_maxima"])
            DspFixtures.assertRel(w.expect["bar"]!!.jsonPrimitive.double, PopDsp.gumbelBar(s), 0.01,
                "${f.name} ${l.role} ${w.kind} bar")
        }
    }

    @Test fun degenerateFallsBack() {
        // all equal: no fit -> max; floor applies
        assertEquals(PopConstants.FLOOR_SCORE, PopDsp.gumbelBar(DoubleArray(64) { 0.01 }))
        assertEquals(0.2, PopDsp.gumbelBar(DoubleArray(64) { 0.2 }))
        assertEquals(null, Gumbel.fit(DoubleArray(64) { 0.2 }))
    }
}
