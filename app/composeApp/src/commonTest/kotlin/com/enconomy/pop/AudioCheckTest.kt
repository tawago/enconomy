package com.enconomy.pop

import kotlin.math.abs
import kotlin.math.pow
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

    /** Same numbers as server jbl250.tune_limit on this toy vector (bound 2.25, margin 0.999). */
    @Test fun tuneLimitMatchesServerRule() {
        val b = doubleArrayOf(0.1, -0.2, 0.3, 0.0, -0.05)
        val t = doubleArrayOf(0.25, 0.3, -0.2, 0.0, -0.4)
        for ((db, g) in listOf(0.0 to 1.0, 4.0 to 10.0.pow(0.2), 8.0 to 2.25 * 0.999, 12.0 to 2.25 * 0.999)) {
            val (gg, gMax) = TuneBoost.limit(b, t, db)
            assertEquals(2.25, gMax, 1e-12)
            assertEquals(g, gg, 1e-12, "tune_db $db")
        }
    }

    @Test fun tuneBoostKeepsBedAndPeak() {
        for (sr in listOf(44100, 48000)) for (role in listOf('A', 'B')) {
            val (bed, tune) = TestSound.parts(sr, role)
            val base = TestSound.generate(sr, role)
            val m0 = TestSound.generate(sr, 0.0, role)
            assertTrue(base.contentEquals(m0.play))
            for (i in base.indices) assertEquals(base[i].toDouble(), bed[i] + tune[i], 1e-6)
            var lastApplied = 0.0
            for (db in TuneBoost.STEPS_DB) {
                val m = TestSound.generate(sr, db, role)
                assertTrue(m.peak <= PopConstants.MAX_PEAK, "peak ${m.peak} at $db")
                assertTrue(m.appliedDb <= db + 1e-9 && m.appliedDb >= lastApplied - 1e-9)
                if (db < m.maxDb) assertEquals(db, m.appliedDb, 1e-9)
                else assertTrue(m.peak > 0.9 * PopConstants.MAX_PEAK, "limited, not clipped")
                val g = 10.0.pow(m.appliedDb / 20)
                for (i in bed.indices) assertEquals(bed[i], m.play[i] - g * tune[i], 1e-6) // bed unchanged
                lastApplied = m.appliedDb
            }
        }
    }
}
