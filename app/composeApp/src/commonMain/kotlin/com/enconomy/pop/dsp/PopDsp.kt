package com.enconomy.pop.dsp

import com.enconomy.pop.PopConstants
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * JBL250 receiver, contract docs/pop-contract.md section 6. Pure Kotlin, DoubleArray, no Android.
 * Python twin: tools/dsp-fixtures/dsp_ref.py (fixtures come from it).
 *
 * Choices the contract leaves open (same in dsp_ref.py):
 *  - round() is ties-to-even everywhere (Python round, kotlin.math.round).
 *  - mask frequency f = bin * (1 / (nfft * (1 / sr))), numpy rfftfreq bit for bit.
 *  - flat runs count samples of a constant run (analysis.py rule); IntRange is [start, end - 1]
 *    (i.e. `start until end`).
 *  - not found -> frame = -1, score = 0.
 */
object PopDsp {
    const val WHY_WINDOW_OUTSIDE = "window_outside_capture"
    const val WHY_BELOW_BAR = "below_bar"
    const val WHY_NO_PEAK = "no_peak"

    private val nullCache = LinkedHashMap<String, List<DoubleArray>>()

    fun codeFrames(sr: Int): Int = pyRound(PopConstants.CODE_S * sr)

    fun nullTemplate(sessionIdHex: String, emitter: Char, attempt: Int, i: Int, sr: Int): DoubleArray =
        NullCodes.template(sessionIdHex, emitter, attempt, i, sr)

    /** The N_NULL nulls of one (session, emitter, attempt, sr), cached (4 entries: self + partner, 2 rates). */
    fun nullTemplates(sessionIdHex: String, emitter: Char, attempt: Int, sr: Int): List<DoubleArray> {
        val key = "$sessionIdHex|$emitter|$attempt|$sr"
        nullCache[key]?.let { return it }
        val v = List(PopConstants.N_NULL) { nullTemplate(sessionIdHex, emitter, attempt, it, sr) }
        if (nullCache.size >= 4) nullCache.remove(nullCache.keys.first())
        nullCache[key] = v
        return v
    }

    /** Search window [w0, w1) clipped to [0, n); step 6.3.1. */
    fun window(expectedFrame: Double, sr: Int, n: Int): IntRange {
        val w0 = pyRound(expectedFrame - PopConstants.SEARCH_PRE_S * sr)
        val w1 = pyRound(expectedFrame + PopConstants.SEARCH_POST_S * sr)
        return max(0, w0) until min(n, w1)
    }

    /** Steps 6.3.1-7 for one window. null when the window has fewer than 3 frames. */
    fun correlate(capture: ShortArray, sr: Int, template: DoubleArray, nulls: List<DoubleArray>,
                  expectedFrame: Double): WindowCorr? {
        val win = window(expectedFrame, sr, capture.size)
        val w0 = win.first
        val w1 = win.last + 1
        if (w1 - w0 < 3) return null
        val L = codeFrames(sr)
        val m = pyRound(PopConstants.SEGMENT_MARGIN_S * sr)
        val a = max(0, w0 - m)
        val b = min(capture.size, w1 + L + m)
        val segN = b - a
        val nfft = Fft.nextPow2(segN + L)
        val h = nfft / 2 + 1
        val mask = BooleanArray(h).also {
            val v = 1.0 / (nfft * (1.0 / sr))
            for (k in 0 until h) {
                val f = k * v
                it[k] = f >= PopConstants.BAND_HZ[0] && f <= PopConstants.BAND_HZ[1]
            }
        }
        val seg = DoubleArray(segN) { capture[a + it] / 32768.0 }
        val sx = Fft.rfft2(seg, null, nfft)
        val xr = sx[0]; val xi = sx[1]
        for (k in 0 until h) if (!mask[k]) { xr[k] = 0.0; xi[k] = 0.0 }
        val xm = Fft.irfft(xr, xi, nfft)
        val cs = DoubleArray(segN + 1)
        for (t in 0 until segN) cs[t + 1] = cs[t] + xm[t] * xm[t]
        val nw = w1 - w0
        val nx = DoubleArray(nw) {
            val n = w0 - a + it
            sqrt(max(cs[min(n + L, segN)] - cs[n], 0.0))
        }
        val eng = Engine(nfft, h, mask, xr, xi, w0 - a, nw, nx)

        val env = DoubleArray(nw)
        val score = DoubleArray(nw)
        val nullMax = DoubleArray(nulls.size)
        // templates go through the rfft two at a time: (real, null0), (null1, null2), ...
        val all = listOf(template) + nulls
        var j = 0
        while (j < all.size) {
            val s = Fft.rfft2(all[j], all.getOrNull(j + 1), nfft)
            eng.score(s[0], s[1], if (j == 0) env else null, if (j == 0) score else null)
                .let { if (j > 0) nullMax[j - 1] = it }
            if (j + 1 < all.size) nullMax[j] = eng.score(s[2], s[3], null, null)
            j += 2
        }
        return WindowCorr(w0, w1, a, b, nfft, env, score, nullMax)
    }

    /** Bar T = max(T_gumbel, max s_i, FLOOR_SCORE); step 6.3.7. */
    fun gumbelBar(nullMaxima: DoubleArray): Double {
        val mx = nullMaxima.maxOrNull() ?: 0.0
        val p = PopConstants.NULL_P / PopConstants.NULL_P_SAFETY
        val tg = Gumbel.fit(nullMaxima)?.let { Gumbel.isf(p, it) }?.takeIf { it.isFinite() } ?: mx
        return maxOf(tg, mx, PopConstants.FLOOR_SCORE)
    }

    /** "first" rule, step 6.3.8: index into the window or -1. */
    fun firstArrival(env: DoubleArray, score: DoubleArray, bar: Double, look: Int): Int {
        if (env.size < 3) return -1
        for (n in 1 until env.size - 1) {
            if (env[n] >= env[n - 1] && env[n] > env[n + 1] && score[n] >= bar) {
                var ref = env[n]
                for (q in n..min(n + look, env.size - 1)) if (env[q] > ref) ref = env[q]
                if (env[n] >= PopConstants.HALF_FRAC * ref) return n
            }
        }
        return -1
    }

    fun measureArrival(capture: ShortArray, sr: Int, template: DoubleArray, nulls: List<DoubleArray>,
                       expectedFrame: Double): Arrival {
        val c = correlate(capture, sr, template, nulls, expectedFrame)
        if (c == null) {
            val w = window(expectedFrame, sr, capture.size)
            return Arrival(false, -1, 0.0, 0.0, 0.0, w.first, w.last + 1, -1, 0.0, WHY_WINDOW_OUTSIDE)
        }
        val bar = gumbelBar(c.nullMaxima)
        val n = firstArrival(c.env, c.score, bar, pyRound(PopConstants.HALF_LOOKAHEAD_S * sr))
        var s = 0
        for (q in c.score.indices) if (c.score[q] > c.score[s]) s = q
        val nmax = c.nullMaxima.maxOrNull() ?: 0.0
        return if (n < 0) {
            Arrival(false, -1, 0.0, bar, nmax, c.w0, c.w1, c.w0 + s, c.score[s],
                if (c.score[s] < bar) WHY_BELOW_BAR else WHY_NO_PEAK)
        } else {
            Arrival(true, c.w0 + n, c.score[n], bar, nmax, c.w0, c.w1, c.w0 + s, c.score[s], null)
        }
    }

    /** Runs of >= round(FLAT_RUN_MIN_S * sr) equal consecutive samples, as `start until end`. */
    fun flatRuns(capture: ShortArray, sr: Int): List<IntRange> {
        val minN = pyRound(PopConstants.FLAT_RUN_MIN_S * sr)
        if (capture.size < minN || minN < 2) return emptyList()
        val out = ArrayList<IntRange>()
        val nd = capture.size - 1
        var i = 0
        while (i < nd) {
            if (capture[i + 1] != capture[i]) { i++; continue }
            var j = i
            while (j < nd && capture[j + 1] == capture[j]) j++
            if (j + 1 - i >= minN) out.add(i until j + 1)
            i = j
        }
        return out
    }

    /** Any run intersecting [lo, hi). */
    fun runsHit(runs: List<IntRange>, lo: Int, hi: Int): Boolean = runs.any { it.first < hi && lo < it.last + 1 }

    /** A: t_BA - t_AA ; B: t_BB - t_AB. */
    fun half(selfArrival: Int, partnerArrival: Int, role: Char): Int = when (role) {
        'A' -> partnerArrival - selfArrival
        'B' -> selfArrival - partnerArrival
        else -> throw IllegalArgumentException("role $role")
    }

    /** Section 8.1 (server side; here for tests/diagnostics): c/2 * (half_A/sr_A - half_B/sr_B) in cm. */
    fun flightCm(halfA: Int, srA: Int, halfB: Int, srB: Int): Double =
        PopConstants.SPEED_OF_SOUND_CM_S / 2.0 * (halfA.toDouble() / srA - halfB.toDouble() / srB)

    /** Section 4.4: frame index in the capture of a monotonic-clock instant. */
    fun expectedFrame(eventNs: Double, captureFrame0Ns: Double, sr: Int): Double =
        (eventNs - captureFrame0Ns) * sr / 1e9

    /** Correlates one template spectrum against the masked segment; returns max score in the window. */
    private class Engine(val nfft: Int, val h: Int, val mask: BooleanArray, val xr: DoubleArray, val xi: DoubleArray,
                         val off: Int, val nw: Int, val nx: DoubleArray) {
        private val zr = DoubleArray(nfft)
        private val zi = DoubleArray(nfft)

        fun score(cr: DoubleArray, ci: DoubleArray, envOut: DoubleArray?, scoreOut: DoubleArray?): Double {
            var p = 0.0
            zr.fill(0.0); zi.fill(0.0)
            for (k in 0 until h) {
                if (!mask[k]) continue
                val r = cr[k]; val i = ci[k]
                val p2 = r * r + i * i
                p += if (k == 0 || k == nfft / 2) p2 else 2 * p2
                // Z = 2 X conj(C)
                zr[k] = 2 * (xr[k] * r + xi[k] * i)
                zi[k] = 2 * (xi[k] * r - xr[k] * i)
            }
            val cn = sqrt(p / nfft)
            Fft.transform(zr, zi, true)
            var mx = Double.NEGATIVE_INFINITY
            for (q in 0 until nw) {
                val re = zr[off + q] / nfft; val im = zi[off + q] / nfft
                val e = sqrt(re * re + im * im)
                val s = e / (nx[q] * cn + 1e-30)
                envOut?.set(q, e)
                scoreOut?.set(q, s)
                if (s > mx) mx = s
            }
            return mx
        }
    }
}

/** One search window. Frames are capture-relative; strongest = argmax score in the window. */
data class Arrival(val found: Boolean, val frame: Int, val score: Double, val bar: Double, val nullMax: Double,
                   val windowLo: Int, val windowHi: Int, val strongestFrame: Int, val strongestScore: Double,
                   val why: String?)

/** Correlation of one window: env/score of the real template over [w0, w1), max score of each null. */
class WindowCorr(val w0: Int, val w1: Int, val segLo: Int, val segHi: Int, val nfft: Int,
                 val env: DoubleArray, val score: DoubleArray, val nullMaxima: DoubleArray)
