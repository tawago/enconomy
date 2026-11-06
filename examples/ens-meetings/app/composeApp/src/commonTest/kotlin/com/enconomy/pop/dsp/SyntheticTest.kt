package com.enconomy.pop.dsp

import com.enconomy.pop.PopConstants
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

/** Synthetic two-phone round: known beds at known frames in noise, with a direct path and later echoes. */
class SyntheticTest {
    private val sid = "c0ffee00".repeat(4)

    private fun bed(role: Char, sr: Int) = PopDsp.nullTemplate("feed".repeat(8), role, 0, 99, sr).let { b ->
        val mx = b.maxOf { abs(it) }
        DoubleArray(b.size) { b[it] / mx }
    }

    private class Noise(var s: Long) {
        fun next(): Double {
            s = s xor (s shl 13); s = s xor (s ushr 7); s = s xor (s shl 17)
            return ((s ushr 11).toDouble() / (1L shl 53).toDouble()) * 2 - 1
        }
    }

    /** onset frame -> (bed, gain) list; direct + 2 echoes (one louder, inside the 5 ms look-ahead). */
    private fun capture(sr: Int, events: List<Pair<Int, DoubleArray>>, seed: Long, noise: Double = 0.003): ShortArray {
        val n = pyRound(PopConstants.CAPTURE_S * sr)
        val x = DoubleArray(n)
        val rnd = Noise(seed)
        for (t in 0 until n) x[t] = noise * rnd.next() + 0.02 * sin(2 * PI * 440.0 * t / sr)   // + an in-tune hum below band
        for ((on, b) in events) {
            for ((d, g) in listOf(0 to 0.05, 90 to 0.07, 600 to 0.04)) {
                for (t in b.indices) {
                    val q = on + d + t
                    if (q in 0 until n) x[q] += g * b[t]
                }
            }
        }
        return ShortArray(n) { (x[it] * 32768).roundToInt().coerceIn(-32768, 32767).toShort() }
    }

    private class Round(val sr: Int, val selfPath: Int, val cross: Int, val errSelf: Int = 17)

    private fun run(r: Round): Pair<PopRound.Step, PopRound.Step> {
        val sr = r.sr
        val bA = bed('A', sr); val bB = bed('B', sr)
        val gap = pyRound(PopConstants.B_PLAY_S * sr)
        // listener A: capture frame0 at 0, A plays at pa; B plays pa + gap
        val paA = pyRound(PopConstants.LEAD_S * sr) + 311
        val capA = capture(sr, listOf(paA + r.selfPath to bA, paA + gap + r.cross to bB), 1)
        val paB = pyRound(PopConstants.LEAD_S * sr) - 205   // B's capture starts later than A's
        val capB = capture(sr, listOf(paB + r.cross to bA, paB + gap + r.selfPath to bB), 2)
        val rA = PopRound(capA, sr, 'A', sid, 0)
        val rB = PopRound(capB, sr, 'B', sid, 0)
        val sA = rA.selfCheck(bA, (paA + r.errSelf).toDouble())
        val sB = rB.selfCheck(bB, (paB + gap - r.errSelf).toDouble())
        assertIs<PopRound.Step.SelfOk>(sA)
        assertIs<PopRound.Step.SelfOk>(sB)
        assertEquals(paA + r.selfPath, sA.arrival.frame)
        assertEquals(r.selfPath - r.errSelf, sA.selfOsDelta)
        assertEquals(paB + gap + r.selfPath, sB.arrival.frame)
        return rA.measurePartner(bB, (paA + gap).toDouble()) to rB.measurePartner(bA, paB.toDouble())
    }

    @Test fun near48k() {
        val (a, b) = run(Round(48000, selfPath = 6, cross = 48))
        assertIs<PopRound.Step.PartnerOk>(a); assertIs<PopRound.Step.PartnerOk>(b)
        val gap = pyRound(0.95 * 48000)
        assertEquals(gap + 48 - 6, a.half)
        assertEquals(gap + 6 - 48, b.half)
        val fl = PopDsp.flightCm(a.half, 48000, b.half, 48000)
        assertTrue(abs(fl - 34300.0 * 42 / 48000) < 1e-9, "flight $fl")
        assertTrue(fl < PopConstants.NEAR_CM)
        // the louder echo 90 frames later is inside the look-ahead but the direct path is kept
        assertTrue(a.arrival.strongestFrame > a.arrival.frame)
    }

    @Test fun far44k() {
        val (a, b) = run(Round(44100, selfPath = 5, cross = 305))
        assertIs<PopRound.Step.PartnerOk>(a); assertIs<PopRound.Step.PartnerOk>(b)
        val fl = PopDsp.flightCm(a.half, 44100, b.half, 44100)
        assertTrue(abs(fl - 34300.0 * 300 / 44100) < 1e-9, "flight $fl")
        assertTrue(fl > PopConstants.NEAR_CM)
    }

    @Test fun failures() {
        val sr = 48000
        val bA = bed('A', sr)
        val on = 30000
        // nothing played: self_not_heard (below the bar)
        val quiet = capture(sr, emptyList(), 3)
        val q = PopRound(quiet, sr, 'A', sid, 0).selfCheck(bA, on.toDouble())
        assertIs<PopRound.Step.Failed>(q)
        assertEquals(DspReason.SELF_NOT_HEARD, q.reason)
        assertEquals(PopDsp.WHY_BELOW_BAR, q.arrival!!.why)
        assertTrue(q.arrival!!.bar >= PopConstants.FLOOR_SCORE)

        val good = capture(sr, listOf(on to bA), 4)
        // dropped block inside [w0, w1 + L)
        val gl = good.copyOf().also { for (i in on + 2000 until on + 2000 + 500) it[i] = 0 }
        assertEquals(DspReason.GLITCH, (PopRound(gl, sr, 'A', sid, 0).selfCheck(bA, on.toDouble()) as PopRound.Step.Failed).reason)
        // a block after w1 + L does not count for the self check
        val w1L = on + pyRound(0.25 * sr) + pyRound(0.25 * sr)
        val late = good.copyOf().also { for (i in w1L + 10 until w1L + 600) it[i] = 0 }
        assertIs<PopRound.Step.SelfOk>(PopRound(late, sr, 'A', sid, 0).selfCheck(bA, on.toDouble()))
        // OS timestamp 100 ms off (still inside the window): mismatch
        val ts = PopRound(good, sr, 'A', sid, 0).selfCheck(bA, (on - 4800).toDouble())
        assertEquals(DspReason.SELF_TIMESTAMP_MISMATCH, (ts as PopRound.Step.Failed).reason)
        // window outside the capture
        val out = PopRound(good, sr, 'A', sid, 0).selfCheck(bA, 10.0 * sr)
        assertEquals(DspReason.CAPTURE_FAILED, (out as PopRound.Step.Failed).reason)
        // wrong capture length
        val short = PopRound(good.copyOf(good.size - 1), sr, 'A', sid, 0).selfCheck(bA, on.toDouble())
        assertEquals(DspReason.CAPTURE_FAILED, (short as PopRound.Step.Failed).reason)
        // wrong code (partner's bed where mine should be): not heard
        val wrong = PopRound(good, sr, 'A', sid, 0).selfCheck(bed('B', sr), on.toDouble())
        assertEquals(DspReason.SELF_NOT_HEARD, (wrong as PopRound.Step.Failed).reason)
        // edge-clipped window still works
        val a = PopDsp.measureArrival(good, sr, bA, PopDsp.nullTemplates(sid, 'A', 0, sr), on.toDouble())
        assertTrue(a.found && a.frame == on)
        val clip = PopDsp.window(100.0, sr, good.size)
        assertEquals(0, clip.first); assertEquals(100 + 12000, clip.last + 1)
    }
}

/** FFT against a naive DFT (radix-2 and Bluestein sizes). */
class FftTest {
    @Test fun matchesDft() {
        for (n in listOf(1, 2, 8, 64, 3, 15, 100, 441, 1000)) {
            val re = DoubleArray(n) { sin(it * 1.7) + 0.3 * cos(it * 0.2) }
            val im = DoubleArray(n) { cos(it * 2.3) }
            val wr = DoubleArray(n); val wi = DoubleArray(n)
            for (k in 0 until n) for (t in 0 until n) {
                val a = -2 * PI * ((k.toLong() * t) % n) / n
                wr[k] += re[t] * cos(a) - im[t] * sin(a)
                wi[k] += re[t] * sin(a) + im[t] * cos(a)
            }
            val xr = re.copyOf(); val xi = im.copyOf()
            Fft.transform(xr, xi, false)
            for (k in 0 until n) {
                assertTrue(abs(xr[k] - wr[k]) < 1e-9 * max(1, n) && abs(xi[k] - wi[k]) < 1e-9 * max(1, n), "n=$n k=$k")
            }
            Fft.transform(xr, xi, true)
            for (t in 0 until n) assertTrue(abs(xr[t] / n - re[t]) < 1e-12 && abs(xi[t] / n - im[t]) < 1e-12, "inv n=$n")
        }
    }

    @Test fun rfft2AndIrfft() {
        val a = DoubleArray(300) { sin(it * 0.37) }
        val b = DoubleArray(250) { cos(it * 1.1) + 0.5 }
        val s = Fft.rfft2(a, b, 512)
        val xa = Fft.irfft(s[0], s[1], 512)
        val xb = Fft.irfft(s[2], s[3], 512)
        for (t in 0 until 512) {
            assertTrue(abs(xa[t] - (if (t < 300) a[t] else 0.0)) < 1e-12)
            assertTrue(abs(xb[t] - (if (t < 250) b[t] else 0.0)) < 1e-12)
        }
        // odd-length irfft (Bluestein path) round trip
        val n = 11025
        val x = DoubleArray(n) { sin(it * 0.01) * cos(it * 0.3) }
        val re = x.copyOf(); val im = DoubleArray(n)
        Fft.transform(re, im, false)
        val y = Fft.irfft(re.copyOf(n / 2 + 1), im.copyOf(n / 2 + 1), n)
        var worst = 0.0
        for (t in 0 until n) worst = max(worst, abs(y[t] - x[t]))
        assertTrue(worst < 1e-11, "odd irfft $worst")
    }
}
