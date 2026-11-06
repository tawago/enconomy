package com.enconomy.pop.dsp

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * Complex FFT, split re/im DoubleArrays, numpy sign convention:
 * forward X_k = sum x_t e^{-2 pi i k t / n}; inverse is unnormalized (caller divides by n).
 * Radix-2 for powers of two, Bluestein (chirp-z over a radix-2 core) otherwise.
 * Tables are cached per size (copy-on-write, safe across threads).
 */
internal object Fft {
    // copy-on-write caches; tables are immutable once built, so concurrent callers only waste a build
    private var radix: Map<Int, Radix2> = emptyMap()
    private var blue: Map<Int, Bluestein> = emptyMap()

    fun isPow2(n: Int) = n > 0 && (n and (n - 1)) == 0

    fun nextPow2(n: Int): Int {
        var m = 1
        while (m < n) m = m shl 1
        return m
    }

    /** In place, length n = re.size. */
    fun transform(re: DoubleArray, im: DoubleArray, inverse: Boolean) {
        val n = re.size
        require(im.size == n && n > 0)
        if (n == 1) return
        if (isPow2(n)) radix2(n).run(re, im, inverse) else bluestein(n).run(re, im, inverse)
    }

    private fun radix2(n: Int): Radix2 = radix[n] ?: Radix2(n).also { radix = radix + (n to it) }
    private fun bluestein(n: Int): Bluestein =
        blue[n] ?: Bluestein(n, radix2(nextPow2(2 * n - 1))).also { blue = blue + (n to it) }

    /**
     * rfft of two real signals at once (zero padded / cut to nfft): packs a + i b, one complex FFT,
     * splits by Hermitian symmetry. Returns one-sided spectra (nfft/2 + 1 bins) as (aRe, aIm, bRe, bIm).
     * [b] may be null.
     */
    fun rfft2(a: DoubleArray, b: DoubleArray?, nfft: Int): Array<DoubleArray> {
        val re = DoubleArray(nfft)
        val im = DoubleArray(nfft)
        a.copyInto(re, 0, 0, minOf(a.size, nfft))
        b?.copyInto(im, 0, 0, minOf(b.size, nfft))
        transform(re, im, false)
        val h = nfft / 2 + 1
        val ar = DoubleArray(h); val ai = DoubleArray(h)
        val br = DoubleArray(h); val bi = DoubleArray(h)
        for (k in 0 until h) {
            val j = if (k == 0) 0 else nfft - k
            val zr = re[k]; val zi = im[k]; val cr = re[j]; val ci = -im[j]   // conj(Z_{N-k})
            ar[k] = 0.5 * (zr + cr); ai[k] = 0.5 * (zi + ci)
            // (Z - conj Z_{N-k}) / 2i
            br[k] = 0.5 * (zi - ci); bi[k] = -0.5 * (zr - cr)
        }
        return arrayOf(ar, ai, br, bi)
    }

    /** numpy irfft: one-sided spectrum (h bins, h >= n/2 + 1 used up to n/2) -> n real samples. */
    fun irfft(specRe: DoubleArray, specIm: DoubleArray, n: Int): DoubleArray {
        val re = DoubleArray(n)
        val im = DoubleArray(n)
        val top = n / 2
        for (k in 0..top) {
            if (k >= specRe.size) break
            re[k] = specRe[k]
            im[k] = if (k == 0 || (n % 2 == 0 && k == top)) 0.0 else specIm[k]   // numpy drops these imag parts
            if (k != 0 && !(n % 2 == 0 && k == top)) {
                re[n - k] = specRe[k]; im[n - k] = -specIm[k]
            }
        }
        transform(re, im, true)
        for (t in 0 until n) re[t] /= n
        return re
    }

    private class Radix2(val n: Int) {
        val cosT = DoubleArray(n / 2) { cos(2.0 * PI * it / n) }
        val sinT = DoubleArray(n / 2) { sin(2.0 * PI * it / n) }
        val rev = IntArray(n).also { r ->
            var bits = 0
            while ((1 shl bits) < n) bits++
            for (i in 0 until n) {
                var x = i; var y = 0
                repeat(bits) { y = (y shl 1) or (x and 1); x = x shr 1 }
                r[i] = y
            }
        }

        fun run(re: DoubleArray, im: DoubleArray, inverse: Boolean) {
            for (i in 0 until n) {
                val j = rev[i]
                if (j > i) {
                    val tr = re[i]; re[i] = re[j]; re[j] = tr
                    val ti = im[i]; im[i] = im[j]; im[j] = ti
                }
            }
            val sgn = if (inverse) 1.0 else -1.0
            var size = 2
            while (size <= n) {
                val half = size / 2
                val step = n / size
                var start = 0
                while (start < n) {
                    var k = 0
                    for (j in start until start + half) {
                        val wr = cosT[k]; val wi = sgn * sinT[k]
                        val l = j + half
                        val xr = re[l] * wr - im[l] * wi
                        val xi = re[l] * wi + im[l] * wr
                        re[l] = re[j] - xr; im[l] = im[j] - xi
                        re[j] += xr; im[j] += xi
                        k += step
                    }
                    start += size
                }
                size = size shl 1
            }
        }
    }

    private class Bluestein(val n: Int, val core: Radix2) {
        val m = core.n
        // chirp w_k = e^{-i pi k^2 / n}; k^2 mod 2n keeps the angle exact for large k
        val wr = DoubleArray(n)
        val wi = DoubleArray(n)
        val bRe: DoubleArray
        val bIm: DoubleArray

        init {
            val twoN = 2L * n
            for (k in 0 until n) {
                val a = PI * ((k.toLong() * k) % twoN).toDouble() / n
                wr[k] = cos(a); wi[k] = -sin(a)
            }
            bRe = DoubleArray(m); bIm = DoubleArray(m)
            bRe[0] = wr[0]; bIm[0] = -wi[0]
            for (k in 1 until n) {
                bRe[k] = wr[k]; bIm[k] = -wi[k]
                bRe[m - k] = wr[k]; bIm[m - k] = -wi[k]
            }
            core.run(bRe, bIm, false)
        }

        fun run(re: DoubleArray, im: DoubleArray, inverse: Boolean) {
            // inverse(x) = conj(forward(conj x))
            val s = if (inverse) -1.0 else 1.0
            val ar = DoubleArray(m)
            val ai = DoubleArray(m)
            for (k in 0 until n) {
                val xr = re[k]; val xi = s * im[k]
                ar[k] = xr * wr[k] - xi * wi[k]
                ai[k] = xr * wi[k] + xi * wr[k]
            }
            core.run(ar, ai, false)
            for (k in 0 until m) {
                val r = ar[k] * bRe[k] - ai[k] * bIm[k]
                val i = ar[k] * bIm[k] + ai[k] * bRe[k]
                ar[k] = r; ai[k] = i
            }
            core.run(ar, ai, true)
            for (k in 0 until n) {
                val cr = ar[k] / m; val ci = ai[k] / m
                re[k] = cr * wr[k] - ci * wi[k]
                im[k] = s * (cr * wi[k] + ci * wr[k])
            }
        }
    }
}
