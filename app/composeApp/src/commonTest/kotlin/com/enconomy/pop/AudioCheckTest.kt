package com.enconomy.pop

import kotlin.math.abs
import kotlin.math.round
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AudioCheckTest {
    @Test fun testSoundShape() {
        for (sr in listOf(44100, 48000)) {
            val x = TestSound.generate(sr)
            assertEquals(AudioTiming.codeFrames(sr), x.size)
            val rms = TestSound.rms(DoubleArray(x.size) { x[it].toDouble() })
            assertEquals(PopConstants.TARGET_RMS, rms, 1e-4)
            assertTrue(x.all { abs(it) < PopConstants.MAX_PEAK })
        }
    }

    /** Capture as the check records it: 0.5 s lead-in, own sound at t0, scaled by [gain], plus hiss. */
    private fun capture(sr: Int, gain: Double): Pair<ShortArray, Double> {
        val n = AudioTiming.captureFrames(sr)
        val rnd = Random(7)
        val x = DoubleArray(n) { rnd.nextDouble(-20.0, 20.0) }
        val play = TestSound.generate(sr)
        val on = round(PopConstants.LEAD_S * sr).toInt() + 96 // a little acoustic + converter delay
        for (i in play.indices) x[on + i] += gain * 32767 * play[i]
        return ShortArray(n) { x[it].coerceIn(-32768.0, 32767.0).toInt().toShort() } to PopConstants.LEAD_S * sr
    }

    @Test fun loudSelfPasses() {
        val sr = 48000
        val (pcm, exp) = capture(sr, 0.5)
        val lv = SelfHear.measure(pcm, sr, exp)
        assertEquals("ok", lv.verdict, "$lv")
        assertTrue(lv.highMarginDb > 40, "$lv")
        assertTrue(lv.lowMarginDb > 40, "$lv")
        assertTrue(lv.floorPeak <= 20, "$lv")
    }

    @Test fun faintSelfIsTooQuiet() {
        val sr = 48000
        val (pcm, exp) = capture(sr, 0.0005) // ~ -60 dB: iPhone X field result
        val lv = SelfHear.measure(pcm, sr, exp)
        assertEquals("too_quiet", lv.verdict, "$lv")
    }
}
