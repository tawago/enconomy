package com.enconomy.pop.dsp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Contract 6.5: flat runs exact vs dsp_ref; glitch fixture hits, clean ones do not. */
class FlatRunTest {
    @Test fun fixtures() {
        for (f in DspFixtures.fixtures) for (l in f.listeners.values) {
            val tag = "${f.name} ${l.role}"
            assertEquals(l.flatRuns, PopDsp.flatRuns(l.capture, l.sr), tag)
            if (f.name == "glitch_synth" && l.role == 'B') {
                assertEquals(1, l.flatRuns.size, tag)
                assertTrue(l.glitch && !l.glitchSelf, tag)
            } else if (f.name != "glitch_synth") {
                assertTrue(l.flatRuns.isEmpty(), tag)
            }
        }
    }

    @Test fun thresholdIsSampleCount() {
        val sr = 48000   // min run 384 samples
        val x = ShortArray(2000) { if (it % 2 == 0) 5 else -5 }
        for (i in 100 until 100 + 383) x[i] = 7
        assertTrue(PopDsp.flatRuns(x, sr).isEmpty())
        for (i in 1000 until 1000 + 384) x[i] = 0
        assertEquals(listOf(1000 until 1384), PopDsp.flatRuns(x, sr))
        assertTrue(PopDsp.runsHit(PopDsp.flatRuns(x, sr), 1383, 1500))
        assertFalse(PopDsp.runsHit(PopDsp.flatRuns(x, sr), 1384, 1500))
        val tail = ShortArray(500) { if (it < 100) it.toShort() else 3 }
        assertEquals(listOf(100 until 500), PopDsp.flatRuns(tail, sr))
    }
}
