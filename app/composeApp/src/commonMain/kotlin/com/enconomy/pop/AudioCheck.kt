package com.enconomy.pop

import com.enconomy.pop.dsp.Fft
import kotlinx.serialization.json.JsonObjectBuilder
import kotlinx.serialization.json.put
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.round
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.random.Random

/** Where the sound goes and how the OS set the session up, as reported right now. */
data class AudioRoute(
    /** "speaker" | "earpiece" | "bluetooth" | "headphones" | "usb" | "other:<type>" | "unknown" */
    val output: String,
    val outputName: String,
    /** Output volume 0..1 (iOS outputVolume, Android STREAM_MUSIC index / max). */
    val volume: Double,
    /** iOS session mode ("measurement" ...) or Android mic source ("unprocessed" ...). */
    val mode: String,
    val sampleRate: Int,
    /** Free text: category, input port, voice processing, override. */
    val detail: String = "",
) {
    val isSpeaker: Boolean get() = output == "speaker"

    fun putMeta(b: JsonObjectBuilder) {
        b.put("out_route", output)
        b.put("out_name", outputName)
        b.put("out_volume", round(volume * 1000) / 1000)
        b.put("session_mode", mode)
        if (detail.isNotEmpty()) b.put("audio_detail", detail)
    }

    companion object {
        val UNKNOWN = AudioRoute("unknown", "", 0.0, "", 0)
    }
}

/**
 * Local stand-in for the server's JBL250 play sound (server/pop/jbl250.py): the public two-note
 * tune (partials < 1800 Hz) plus a 0.25 s random-phase multisine on the 4 Hz grid over 2-18 kHz at
 * −6 dB re tune, faded, scaled to RMS 0.15. Fixed seed; no session needed.
 *
 * Tune boost (server render(tune_db)): bed and tune at the tune_db = 0 scale, then
 * play = bed + g·tune, g = 10^(tune_db/20) peak-limited on the tune only ([TuneBoost]).
 */
object TestSound {
    private val NOTES = mapOf('A' to doubleArrayOf(329.628, 440.0), 'B' to doubleArrayOf(523.251, 391.995))
    private val HARM = doubleArrayOf(1.0, 0.25, 0.08)

    /** Scaled (bed, tune) exactly as the tune_db = 0 sound: that sound is bed + tune. */
    fun parts(sr: Int, role: Char = 'A', seed: Int = 250): Pair<DoubleArray, DoubleArray> {
        val n = AudioTiming.codeFrames(sr)
        val tune = fade(tune(n, sr, role), sr)
        val bed = multisine(n, sr, Random(seed))
        val g = rms(tune) * 10.0.pow(-6.0 / 20) / rms(bed)
        for (i in bed.indices) bed[i] *= g
        fade(bed, sr)
        val s = PopConstants.TARGET_RMS / rms(DoubleArray(n) { tune[it] + bed[it] })
        for (i in 0 until n) { bed[i] *= s; tune[i] *= s }
        return bed to tune
    }

    fun generate(sr: Int, role: Char = 'A', seed: Int = 250): FloatArray {
        val n = AudioTiming.codeFrames(sr)
        val tune = fade(tune(n, sr, role), sr)
        val bed = multisine(n, sr, Random(seed))
        val g = rms(tune) * 10.0.pow(-6.0 / 20) / rms(bed)
        for (i in bed.indices) bed[i] *= g
        fade(bed, sr)
        val sum = DoubleArray(n) { tune[it] + bed[it] }
        val s = PopConstants.TARGET_RMS / rms(sum)
        return FloatArray(n) { (s * sum[it]).toFloat() }
    }

    /** Test sound with the tune boosted by [tuneDb] (0 = [generate] exactly). */
    fun generate(sr: Int, tuneDb: Double, role: Char = 'A', seed: Int = 250): TuneBoost.Mix {
        if (tuneDb == 0.0) {
            val x = generate(sr, role, seed)
            val (bed, tune) = parts(sr, role, seed)
            return TuneBoost.Mix(x, 0.0, 0.0, TuneBoost.limit(bed, tune).second, x.maxOf { abs(it) }.toDouble())
        }
        val (bed, tune) = parts(sr, role, seed)
        return TuneBoost.mix(bed, tune, tuneDb)
    }

    private fun raised(t: Double, T: Double) = 0.5 * (1 - cos(PI * (t / T).coerceIn(0.0, 1.0)))

    private fun tune(n: Int, sr: Int, role: Char): DoubleArray {
        val out = DoubleArray(n)
        val notes = NOTES[role] ?: error("role $role")
        for ((j, f0) in notes.withIndex()) {
            val on = 0.01 + j * 0.10
            val off = if (j == notes.size - 1) 0.24 - 0.04 else on + 0.10
            for (i in 0 until n) {
                val ta = i.toDouble() / sr
                val t = ta - on
                if (t < 0) continue
                val env = raised(t, 0.012) * exp(-t / 0.10) * (1.0 - raised(ta - off, 0.04))
                for ((k, a) in HARM.withIndex()) {
                    val f = (k + 1) * f0
                    if (f >= 1800.0) break
                    out[i] += a * env * sin(2 * PI * f * t)
                }
            }
        }
        val s = PopConstants.TARGET_RMS / rms(out)
        for (i in out.indices) out[i] *= s
        return out
    }

    private fun multisine(n: Int, sr: Int, rng: Random): DoubleArray {
        val dur = PopConstants.CODE_S
        val h = n / 2 + 1
        val re = DoubleArray(h)
        val im = DoubleArray(h)
        val k0 = ceil(PopConstants.BAND_HZ[0] * dur).toInt()
        val k1 = (PopConstants.BAND_HZ[1] * dur).toInt()
        for (k in k0..k1) {
            if (k >= n / 2) break
            val ph = rng.nextDouble() * 2 * PI
            re[k] = cos(ph); im[k] = sin(ph)
        }
        return Fft.irfft(re, im, n)
    }

    private fun fade(x: DoubleArray, sr: Int): DoubleArray {
        val n = maxOf(1, round(PopConstants.FADE_S * sr).toInt())
        for (i in 0 until n) {
            val r = 0.5 * (1.0 - cos(PI * (i + 0.5) / n))
            x[i] *= r
            x[x.size - 1 - i] *= r
        }
        return x
    }

    fun rms(x: DoubleArray): Double = sqrt(x.sumOf { it * it } / x.size)
}

/**
 * Tune-only boost, same rule as server jbl250.tune_limit/render: the bed is never scaled; if
 * max|bed + g·tune| would pass MAX_PEAK, g drops to the exact per-sample bound × 0.999. No clipping.
 */
object TuneBoost {
    /** Selector steps on the audio check screen. */
    val STEPS_DB = doubleArrayOf(0.0, 4.0, 8.0, 12.0)
    const val MARGIN = 0.999

    /** [play] = bed + g·tune; applied/max in dB (max = exact peak bound); peak = max|play|. */
    class Mix(val play: FloatArray, val requestedDb: Double, val appliedDb: Double, val maxDb: Double, val peak: Double)

    /** (g, gMax): gMax = min over samples of (P − b·sign t)/|t|; g = requested gain if ≤ gMax, else gMax·0.999. */
    fun limit(bed: DoubleArray, tune: DoubleArray, tuneDb: Double = 0.0, maxPeak: Double = PopConstants.MAX_PEAK): Pair<Double, Double> {
        var gMax = Double.POSITIVE_INFINITY
        for (i in bed.indices) {
            val t = tune[i]
            if (t == 0.0) continue
            val v = (maxPeak - bed[i] * (if (t > 0) 1.0 else -1.0)) / abs(t)
            if (v < gMax) gMax = v
        }
        val g = 10.0.pow(tuneDb / 20)
        return (if (g <= gMax) g else maxOf(0.0, gMax * MARGIN)) to gMax
    }

    fun mix(bed: DoubleArray, tune: DoubleArray, tuneDb: Double): Mix {
        val (g, gMax) = limit(bed, tune, tuneDb)
        val y = FloatArray(bed.size) { (bed[it] + g * tune[it]).toFloat() }
        return Mix(y, tuneDb, db(g), db(gMax), y.maxOf { abs(it) }.toDouble())
    }

    fun db(g: Double): Double = if (g > 0) 20 * log10(g) else Double.NEGATIVE_INFINITY
}

/**
 * How loud this phone hears its own sound. Levels are band RMS in dBFS (20·log10(rms / 32768)).
 * low = 200-1600 Hz (the tune), high = 2-18 kHz (the bed the partner correlates with).
 * floor = the quiet lead-in before t0 (capture 0.02 s .. LEAD_S − 0.05 s, and before the own onset).
 * self = loudest CODE_S window within −0.1 s .. +0.15 s of the expected own onset.
 */
data class SelfHear(
    val floorLowDb: Double,
    val floorHighDb: Double,
    val lowDb: Double,
    val highDb: Double,
    /** Max |x| (int16) in the self window and in the floor window. */
    val peak: Int,
    val floorPeak: Int,
) {
    val lowMarginDb: Double get() = lowDb - floorLowDb
    val highMarginDb: Double get() = highDb - floorHighDb
    val peakDb: Double get() = db(peak.toDouble())

    /** "ok" | "weak" | "too_quiet", on the 2-18 kHz margin (the part the partner needs). */
    val verdict: String get() = when {
        highMarginDb >= OK_MARGIN_DB -> "ok"
        highMarginDb >= WEAK_MARGIN_DB -> "weak"
        else -> "too_quiet"
    }

    fun putMeta(b: JsonObjectBuilder) {
        b.put("self_hear_low_db", r1(lowDb))
        b.put("self_hear_high_db", r1(highDb))
        b.put("floor_low_db", r1(floorLowDb))
        b.put("floor_high_db", r1(floorHighDb))
        b.put("self_hear_peak", peak)
        b.put("floor_peak", floorPeak)
        b.put("self_hear_verdict", verdict)
    }

    companion object {
        /** A phone speaker 1-2 cm from its own mic clears the room floor by far more than this. */
        const val OK_MARGIN_DB = 30.0
        const val WEAK_MARGIN_DB = 15.0
        val LOW_HZ = doubleArrayOf(200.0, 1600.0)

        fun db(rms: Double): Double = if (rms <= 0) -120.0 else maxOf(-120.0, 20 * log10(rms / 32768.0))
        fun r1(x: Double) = round(x * 10) / 10

        /** [expectedSelf] = own onset, frames in [pcm] (Capture.expectedSelf()). */
        fun measure(pcm: ShortArray, sr: Int, expectedSelf: Double): SelfHear {
            val n = pcm.size
            val x = DoubleArray(n) { pcm[it].toDouble() }
            val low = bandpass(x, sr, LOW_HZ[0], LOW_HZ[1])
            val high = bandpass(x, sr, PopConstants.BAND_HZ[0], PopConstants.BAND_HZ[1])
            val on = expectedSelf.toInt()
            val f0 = (0.02 * sr).toInt().coerceIn(0, n)
            val f1 = minOf(((PopConstants.LEAD_S - 0.05) * sr).toInt(), on - (0.05 * sr).toInt()).coerceIn(f0, n)
            val w = AudioTiming.codeFrames(sr)
            val s0 = (on - (0.10 * sr).toInt()).coerceIn(0, maxOf(0, n - w))
            val s1 = (on + (0.15 * sr).toInt()).coerceIn(s0, maxOf(0, n - w))
            val lowMax = maxWindowRms(low, w, s0, s1)
            val highMax = maxWindowRms(high, w, s0, s1)
            var pk = 0
            for (i in s0 until minOf(n, s1 + w)) pk = maxOf(pk, abs(pcm[i].toInt()))
            var fpk = 0
            for (i in f0 until f1) fpk = maxOf(fpk, abs(pcm[i].toInt()))
            return SelfHear(db(rmsOf(low, f0, f1)), db(rmsOf(high, f0, f1)), db(lowMax), db(highMax), pk, fpk)
        }

        private fun rmsOf(x: DoubleArray, a: Int, b: Int): Double {
            if (b <= a) return 0.0
            var s = 0.0
            for (i in a until b) s += x[i] * x[i]
            return sqrt(s / (b - a))
        }

        private fun maxWindowRms(x: DoubleArray, w: Int, from: Int, to: Int): Double {
            if (x.size < w || w <= 0) return 0.0
            var s = 0.0
            for (i in from until from + w) s += x[i] * x[i]
            var best = s
            for (i in from + 1..to) {
                s += x[i + w - 1] * x[i + w - 1] - x[i - 1] * x[i - 1]
                if (s > best) best = s
            }
            return sqrt(maxOf(0.0, best) / w)
        }

        /** Brick-wall FFT band-pass (whole signal, zero padded to a power of two). */
        internal fun bandpass(x: DoubleArray, sr: Int, lo: Double, hi: Double): DoubleArray {
            val nfft = Fft.nextPow2(x.size)
            val (re, im) = Fft.rfft2(x, null, nfft).let { it[0] to it[1] }
            for (k in re.indices) {
                val f = k.toDouble() * sr / nfft
                if (f < lo || f > hi) { re[k] = 0.0; im[k] = 0.0 }
            }
            return Fft.irfft(re, im, nfft).copyOf(x.size)
        }
    }
}

/**
 * Self timestamp offset exactly as a POPT v2 run computes it: [PopRound2.selfCheck] on the capture with the
 * check sound's own bed as the int8 code (server code_from_template), p_self = round(expected_self) from the
 * play onset + rec frame0 timestamps, a_self = earliest pass. [frames] = self_os_delta = a_self − p_self.
 */
data class SelfOffset(
    val sr: Int,
    val pSelf: Int?,
    val aSelf: Int?,
    /** Null = no v2 rate for [sr] or own sound not found (see [reason]). */
    val frames: Int?,
    /** 2 ms in frames (v2 delta, the option A bound). */
    val deltaFrames: Int,
    val reason: String?,
    val score: Double = 0.0,
) {
    val ms: Double? get() = frames?.let { it * 1000.0 / sr }
    val within: Boolean? get() = frames?.let { abs(it) <= deltaFrames }

    fun line(): String {
        val f = frames ?: return "offset ? (${reason ?: "not measured"})"
        return "offset $f frames (${round(ms!! * 100) / 100} ms) — within 2 ms: ${if (within == true) "yes" else "no"}"
    }

    companion object {
        fun measure(cap: Capture, bed: DoubleArray): SelfOffset {
            val sr = cap.sr
            val rate = com.enconomy.pop.dsp.Popt2Rates.builtIn[sr]
                ?: return SelfOffset(sr, null, null, null, Popt2Config.DELTA_MS * sr / 1000, "no v2 rate for $sr Hz")
            val code = com.enconomy.pop.dsp.Popt2Code.fromTemplate(bed, sr)
            val r = com.enconomy.pop.dsp.PopRound2(cap.pcm, rate, 'A')
            val st = r.selfCheck(code, cap.expectedSelf())
            val a = r.self?.frame
            val p = r.pSelf
            val reason = (st as? com.enconomy.pop.dsp.PopRound2.Step.Failed)?.reason
            return SelfOffset(sr, p, a, if (a != null && p != null) a - p else null, rate.delta, reason, r.self?.score ?: 0.0)
        }
    }
}

/** One audio check: route/session as played, self-hear levels, verdict text. */
data class AudioCheckResult(
    val route: AudioRoute,
    val levels: SelfHear,
    val tsSource: String,
    val latencyMs: Double?,
    val warnings: List<String>,
    /** Tune boost as played: requested / applied dB (after peak limiting) and play peak (full scale 1). */
    val tuneRequestedDb: Double = 0.0,
    val tuneAppliedDb: Double = 0.0,
    val playPeak: Double = 0.0,
    val offset: SelfOffset? = null,
    /** Audio path as opened: backend, sharing/mmap (AAudio), requested/granted input preset. */
    val path: List<Pair<String, String>> = emptyList(),
) {
    val verdict: String get() = when {
        !route.isSpeaker -> "Wrong output: ${route.output}"
        levels.verdict == "ok" -> "OK"
        levels.verdict == "weak" -> "Weak"
        else -> "Too quiet"
    }
    val pass: Boolean get() = route.isSpeaker && levels.verdict == "ok"
}
