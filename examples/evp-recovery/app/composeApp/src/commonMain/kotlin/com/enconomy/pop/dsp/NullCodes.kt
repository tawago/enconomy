package com.enconomy.pop.dsp

import com.enconomy.pop.PopConstants
import com.enconomy.pop.sha256
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.round
import kotlin.math.sin

/**
 * Contract 6.2: live-null codes from a SHA-256 stream, bit-compatible with dsp_ref.null_template.
 * Same family as the real bed: 0.25 s random-phase multisine on the 4 Hz grid over 2-18 kHz, faded.
 */
internal object NullCodes {
    const val K_LO = 500   // 2000 Hz * 0.25 s

    fun seed(sessionIdHex: String, emitter: Char, attempt: Int, i: Int): ByteArray =
        sha256("pop-null-v1|$sessionIdHex|$emitter|$attempt|$i".encodeToByteArray())

    /** u32 BE words of sha256(seed || u32be(0)) || sha256(seed || u32be(1)) || ... as [0, 1). */
    fun unitWords(seed: ByteArray, count: Int): DoubleArray {
        val out = DoubleArray(count)
        val buf = seed.copyOf(seed.size + 4)
        var j = 0
        var w = 0
        while (w < count) {
            buf[seed.size] = (j ushr 24).toByte(); buf[seed.size + 1] = (j ushr 16).toByte()
            buf[seed.size + 2] = (j ushr 8).toByte(); buf[seed.size + 3] = j.toByte()
            val d = sha256(buf)
            var q = 0
            while (q < 8 && w < count) {
                val u = ((d[4 * q].toLong() and 0xff) shl 24) or ((d[4 * q + 1].toLong() and 0xff) shl 16) or
                    ((d[4 * q + 2].toLong() and 0xff) shl 8) or (d[4 * q + 3].toLong() and 0xff)
                out[w++] = u.toDouble() / 4294967296.0
                q++
            }
            j++
        }
        return out
    }

    fun template(sessionIdHex: String, emitter: Char, attempt: Int, i: Int, sr: Int): DoubleArray {
        val n = pyRound(PopConstants.CODE_S * sr)
        val kHi = minOf(4500, n / 2 - 1)
        val ph = unitWords(seed(sessionIdHex, emitter, attempt, i), kHi - K_LO + 1)
        val h = n / 2 + 1
        val sRe = DoubleArray(h)
        val sIm = DoubleArray(h)
        for (k in K_LO..kHi) {
            val a = 2.0 * PI * ph[k - K_LO]
            sRe[k] = cos(a); sIm[k] = sin(a)
        }
        return fade(Fft.irfft(sRe, sIm, n), sr)
    }

    /** Raised-cosine edges, F = max(1, round(FADE_S * sr)) (melody_probes._fade). */
    fun fade(x: DoubleArray, sr: Int): DoubleArray {
        val f = max(1, pyRound(PopConstants.FADE_S * sr))
        for (m in 0 until f) {
            val r = 0.5 * (1.0 - cos(PI * (m + 0.5) / f))
            x[m] *= r
            x[x.size - 1 - m] *= r
        }
        return x
    }
}

/** Python round(): ties to even (kotlin.math.round is IEEE rint). */
internal fun pyRound(x: Double): Int = round(x).toInt()
