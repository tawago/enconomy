package com.enconomy.pop.dsp

import com.enconomy.pop.fromB64
import kotlin.math.abs
import kotlin.math.sqrt

/**
 * POPT v2 integer arrival rule (docs/pop-transcript-v2.md §3; spike optionA-v2/oa_rate.py earliest()).
 * The option A circuit re-runs it on the committed int16 samples, so it is exact integer math.
 *
 *   I_k = Σ_{n<L} cI[n]·x[k+n]      Q_k = Σ cQ[n]·x[k+n]          (int8 codes from the server)
 *   y[m] = Σ_{t<63} h[t]·x[m−31+t]  E_k = Σ_{m=k}^{k+L−1} y[m]²     (63-tap int FIR, centred)
 *   pass(k) ⇔ (I_k² + Q_k²)·B ≥ E_k·Σ cI²                          (score ≥ 9 %, exact 128-bit)
 *   arrival = smallest k in [lo, hi) with pass(k). x outside the capture = 0 (as the tree pads).
 */
class Popt2Rate(val sr: Int, val L: Int, val B: Long, val delta: Int, val wpre: Int, val wpost: Int, val h: IntArray) {
    init {
        require(h.size == Popt2Rule.TAPS && L > 0 && B > 0 && B < (1L shl 32)) { "bad v2 rate $sr" }
    }

    /** Same numbers (the /v1/config popt2_rates check). */
    fun sameAs(o: Popt2Rate) = sr == o.sr && L == o.L && B == o.B && delta == o.delta && wpre == o.wpre &&
        wpost == o.wpost && h.contentEquals(o.h)
}

object Popt2Rates {
    /** Server pop/popt2.RATES = oa_rate.params(sr). Hard-coded: the float FIR design is not portable. */
    val builtIn: Map<Int, Popt2Rate> = mapOf(
        48000 to Popt2Rate(48000, 12000, 4474747, 96, 7200, 12000, intArrayOf(
            0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 2, 0, 2, 2, 0, 4, -1, 0, 2, -7, 0, -5, -13, 0, -19, -13, 0, -45,
            27, 127, 27, -45, 0, -13, -19, 0, -13, -5, 0, -7, 2, 0, -1, 4, 0, 2, 2, 0, 2, 1, 0, 1, 0, 0, 0, 0,
            0, 0, 0, 0, 0)),
        44100 to Popt2Rate(44100, 11025, 3792174, 88, 6615, 11025, intArrayOf(
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 2, 1, 1, 3, 0, 4, -1, 0, 1, -7, 1, -12, -6, -8, -22, 4, -40,
            15, 127, 15, -40, 4, -22, -8, -6, -12, 1, -7, 1, 0, -1, 4, 0, 3, 1, 1, 2, 0, 1, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0)),
    )
}

/** One emitter's int8 template pair at the listener's rate (own_code / partner_code on the wire). */
class Popt2Code(val cI: ByteArray, val cQ: ByteArray) {
    init {
        require(cI.isNotEmpty() && cI.size == cQ.size) { "code lengths ${cI.size}/${cQ.size}" }
    }

    val n: Int get() = cI.size

    /** Σ cI² (cI only, as the circuit). */
    val cn2: Long = cI.fold(0L) { a, v -> a + v.toLong() * v }

    companion object {
        fun fromB64(cIb64: String, cQb64: String, n: Int): Popt2Code {
            val c = Popt2Code(cIb64.fromB64(), cQb64.fromB64())
            require(c.n == n) { "code n ${c.n} != $n" }
            return c
        }
    }
}

/** [frame] null = no lag passed. [score] = diagnostic score at [frame] (0 when none). */
data class Arrival2(val frame: Int?, val score: Double, val lo: Int, val hi: Int)

object Popt2Rule {
    const val TAPS = 63
    const val HM = 31
    const val T0 = 0.09
    /** 512 · 127 · 32768 < 2^31: int8 × int16 products summed in Int for this many terms. */
    private const val CHUNK = 512

    /** (I² + Q²)·B ≥ E·cn2, exact. All inputs ≥ 0 except I, Q; |I|, |Q| < 2^62, B, cn2 < 2^32. */
    fun passes(i: Long, q: Long, e: Long, cn2: Long, b: Long): Boolean {
        val u = U128()
        u.sq(i); val iH = u.hi; val iL = u.lo
        u.sq(q)
        val lo = iL + u.lo
        val hi = iH + u.hi + (if (lo < iL) 1uL else 0uL)
        u.hi = hi; u.lo = lo
        u.timesSmall(b.toULong())
        val lHi = u.hi; val lLo = u.lo
        u.mul(e.toULong(), cn2.toULong())
        return if (lHi != u.hi) lHi > u.hi else lLo >= u.lo
    }

    /** sqrt((I²+Q²)·g² / (E·cn2)), g² ≈ B·T0². Diagnostics only (meta); 0 when E = 0. */
    fun score(i: Long, q: Long, e: Long, cn2: Long, b: Long): Double {
        if (e == 0L || cn2 == 0L) return 0.0
        val env = i.toDouble() * i + q.toDouble() * q
        return T0 * sqrt(env * b / (e.toDouble() * cn2))
    }

    /**
     * Earliest pass in [lo, hi) on [x] (spike oa_rate.earliest).
     *
     * I/Q for all lags come from one float FFT correlation first. A lag is skipped only when it fails even
     * with |I|, |Q| each enlarged by [fftSlack] (≥ 1, far above the FFT rounding error); every other lag,
     * in order, gets the exact integer I/Q and the exact test. So the answer is the exact rule's.
     * [screen] = false runs the exact rule on every lag (tests).
     */
    fun earliest(x: ShortArray, code: Popt2Code, lo: Int, hi: Int, rate: Popt2Rate, screen: Boolean = true): Arrival2 {
        val L = rate.L
        require(code.n == L) { "code n ${code.n} != L $L" }
        val k = hi - lo
        if (k <= 0) return Arrival2(null, 0.0, lo, hi)
        // xs[j] = x[lo − HM + j], j < K + L − 1 + 2·HM
        val base = lo - HM
        val xs = IntArray(k + L - 1 + 2 * HM) { j -> val i = base + j; if (i in x.indices) x[i].toInt() else 0 }
        // y[j] centred on frame lo + j, j < K + L − 1
        val h = rate.h
        val ny = k + L - 1
        val cs = LongArray(ny + 1)
        for (j in 0 until ny) {
            var y = 0
            for (t in 0 until TAPS) y += h[t] * xs[j + t]
            cs[j + 1] = cs[j] + y.toLong() * y
        }
        val cI = IntArray(L) { code.cI[it].toInt() }
        val cQ = IntArray(L) { code.cQ[it].toInt() }
        val cn2 = code.cn2
        val approx = if (screen) fftIq(xs, cI, cQ, k, L) else null
        for (j in 0 until k) {
            val e = cs[j + L] - cs[j]
            if (approx != null) {
                val a = abs(approx.re[j]) + approx.slack
                val b = abs(approx.im[j]) + approx.slack
                if ((a * a + b * b) * rate.B * (1 + 1e-9) < e.toDouble() * cn2) continue
            }
            val off = HM + j
            var sI = 0L
            var sQ = 0L
            var n0 = 0
            while (n0 < L) {
                val n1 = minOf(L, n0 + CHUNK)
                var aI = 0
                var aQ = 0
                for (n in n0 until n1) {
                    val v = xs[off + n]
                    aI += cI[n] * v
                    aQ += cQ[n] * v
                }
                sI += aI; sQ += aQ
                n0 = n1
            }
            if (passes(sI, sQ, e, cn2, rate.B)) return Arrival2(lo + j, score(sI, sQ, e, cn2, rate.B), lo, hi)
        }
        return Arrival2(null, 0.0, lo, hi)
    }

    private class Iq(val re: DoubleArray, val im: DoubleArray, val slack: Double)

    /**
     * I_j + i·Q_j ≈ IFFT(conj(FFT(cI − i·cQ)) · FFT(seg)) / n for j < K, seg = x[lo .. lo + K + L − 2]
     * (no wrap: j + n ≤ K + L − 2 < nfft). slack = 1 + 1e-9·‖seg‖·‖c‖, orders above the radix-2 error
     * bound (~ log2(n)·2^-53·‖seg‖·‖c‖).
     */
    private fun fftIq(xs: IntArray, cI: IntArray, cQ: IntArray, k: Int, L: Int): Iq {
        val segN = k + L - 1
        val nfft = Fft.nextPow2(segN)
        val xr = DoubleArray(nfft)
        val xi = DoubleArray(nfft)
        var nx = 0.0
        for (j in 0 until segN) { val v = xs[HM + j].toDouble(); xr[j] = v; nx += v * v }
        val vr = DoubleArray(nfft)
        val vi = DoubleArray(nfft)
        var nc = 0.0
        for (n in 0 until L) { vr[n] = cI[n].toDouble(); vi[n] = -cQ[n].toDouble(); nc += vr[n] * vr[n] + vi[n] * vi[n] }
        Fft.transform(xr, xi, false)
        Fft.transform(vr, vi, false)
        for (f in 0 until nfft) {
            // conj(V)·X
            val ar = vr[f]; val ai = -vi[f]
            val br = xr[f]; val bi = xi[f]
            xr[f] = ar * br - ai * bi
            xi[f] = ar * bi + ai * br
        }
        Fft.transform(xr, xi, true)
        val inv = 1.0 / nfft
        val re = DoubleArray(k) { xr[it] * inv }
        val im = DoubleArray(k) { xi[it] * inv }
        return Iq(re, im, 1.0 + 1e-9 * sqrt(nx) * sqrt(nc))
    }

    /** Unsigned 128-bit scratch. */
    private class U128 {
        var hi = 0uL
        var lo = 0uL

        /** this = a·b (unsigned 64 × 64). */
        fun mul(a: ULong, b: ULong) {
            val m = 0xFFFFFFFFuL
            val a0 = a and m; val a1 = a shr 32
            val b0 = b and m; val b1 = b shr 32
            val p00 = a0 * b0
            val p01 = a0 * b1
            val p10 = a1 * b0
            val p11 = a1 * b1
            val mid = (p00 shr 32) + (p01 and m) + (p10 and m)
            lo = (p00 and m) or (mid shl 32)
            hi = p11 + (p01 shr 32) + (p10 shr 32) + (mid shr 32)
        }

        fun sq(v: Long) {
            val a = (if (v < 0) -v else v).toULong()
            mul(a, a)
        }

        /** this ·= s (the product must stay < 2^128). */
        fun timesSmall(s: ULong) {
            val h = hi * s
            mul(lo, s)
            hi += h
        }
    }
}
