package com.enconomy.pop.dsp

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.ln1p
import kotlin.math.sqrt

/** Contract 6.4: Gumbel (right) MLE, the scipy gumbel_r.fit equations, Newton on beta. */
internal object Gumbel {
    class Fit(val loc: Double, val scale: Double)

    /** null if the fit does not converge or is non-finite. */
    fun fit(s: DoubleArray): Fit? {
        val n = s.size
        if (n < 2) return null
        val mean = s.average()
        var v = 0.0
        for (x in s) v += (x - mean) * (x - mean)
        val std = sqrt(v / n)
        if (!(std > 0.0) || !std.isFinite()) return null
        val sMin = s.min()
        var beta = std * sqrt(6.0) / PI
        var ok = false
        for (it in 0 until 200) {
            // d = s - sMin, w = e^{-d/b}: g(b) = b - mean + sMin + sum d w / sum w,
            // g'(b) = 1 + (sum d^2 w * sum w - (sum d w)^2) / (b^2 (sum w)^2)
            var sw = 0.0; var ssw = 0.0; var sssw = 0.0
            for (x in s) {
                val d = x - sMin
                val w = exp(-d / beta)
                sw += w; ssw += d * w; sssw += d * d * w
            }
            val g = beta - (mean - sMin) + ssw / sw
            val dg = 1.0 + (sssw * sw - ssw * ssw) / (beta * beta * sw * sw)
            var step = g / dg
            if (!step.isFinite()) return null
            var next = beta - step
            while (next <= 0.0) { step /= 2; next = beta - step }   // stay positive
            val done = abs(next - beta) < 1e-10 * beta
            beta = next
            if (done) { ok = true; break }
        }
        if (!ok || !beta.isFinite()) return null
        var sw = 0.0
        for (x in s) sw += exp(-(x - sMin) / beta)
        val loc = sMin - beta * ln(sw / n)
        return if (loc.isFinite()) Fit(loc, beta) else null
    }

    fun isf(p: Double, f: Fit): Double = f.loc - f.scale * ln(-ln1p(-p))
}
