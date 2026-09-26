package com.enconomy.pop.dsp

import com.enconomy.pop.PopConstants
import com.enconomy.pop.sha256
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/** Failure reasons the phone can post (contract 6.6 / 8.3). */
object DspReason {
    const val CAPTURE_FAILED = "capture_failed"
    const val GLITCH = "glitch"
    const val SELF_NOT_HEARD = "self_not_heard"
    const val SELF_TIMESTAMP_MISMATCH = "self_timestamp_mismatch"
    const val PARTNER_NOT_HEARD = "partner_not_heard"
}

/**
 * Contract 6.6 steps 1-8 for one phone and one attempt. Commit (step 5) sits between
 * [selfCheck] and [measurePartner]; the caller does it and fetches the partner bed.
 *
 * [requireCaptureFrames] = false skips the exact-length check (fixtures hold crops);
 * [selfOsTolFrames] defaults to SELF_OS_TOL_MS (fixtures from the web prototype sit ~90 ms off).
 */
class PopRound(
    val capture: ShortArray,
    val sr: Int,
    val role: Char,
    val sessionIdHex: String,
    val attempt: Int,
    requireCaptureFrames: Boolean = true,
    val selfOsTolFrames: Double = PopConstants.SELF_OS_TOL_MS * sr / 1000.0,
    /** Enrollment calibration, µs (0 = none): the check is |self_os_delta − cal_frames| ≤ tol. */
    val calUs: Long = 0,
) {
    sealed class Step {
        data class Failed(val reason: String, val arrival: Arrival? = null) : Step()
        data class SelfOk(val arrival: Arrival, val selfOsDelta: Int) : Step()
        data class PartnerOk(val arrival: Arrival, val half: Int) : Step()
    }

    val partnerRole: Char = if (role == 'A') 'B' else 'A'
    val captureOk: Boolean = !requireCaptureFrames || capture.size == pyRound(PopConstants.CAPTURE_S * sr)
    /** sha256 of the capture as int16 LE bytes. */
    val recSha256: ByteArray by lazy { sha256(pcm16Le(capture)) }
    val flatRuns: List<IntRange> by lazy { PopDsp.flatRuns(capture, sr) }

    var self: Arrival? = null
        private set
    var partner: Arrival? = null
        private set
    private var selfWin: IntRange? = null

    /** Steps 1-4. [nulls] = PopDsp.nullTemplates(sessionIdHex, role, attempt, sr), built here when not given. */
    fun selfCheck(ownBed: DoubleArray, expectedSelf: Double, nulls: List<DoubleArray>? = null): Step {
        if (!captureOk || sr !in PopConstants.SR_MIN..PopConstants.SR_MAX) return Step.Failed(DspReason.CAPTURE_FAILED)
        val L = PopDsp.codeFrames(sr)
        val w = PopDsp.window(expectedSelf, sr, capture.size)
        if (w.last + 1 - w.first < 3) return Step.Failed(DspReason.CAPTURE_FAILED)
        selfWin = w
        if (PopDsp.runsHit(flatRuns, w.first, w.last + 1 + L)) return Step.Failed(DspReason.GLITCH)
        val a = PopDsp.measureArrival(capture, sr, ownBed,
            nulls ?: PopDsp.nullTemplates(sessionIdHex, role, attempt, sr), expectedSelf)
        self = a
        if (!a.found) return Step.Failed(DspReason.SELF_NOT_HEARD, a)
        val delta = pyRound(a.frame - expectedSelf)
        if (abs(delta - calUs * sr / 1e6) > selfOsTolFrames) return Step.Failed(DspReason.SELF_TIMESTAMP_MISMATCH, a)
        return Step.SelfOk(a, delta)
    }

    /** Steps 6-8, after commit. Requires a passing [selfCheck]. [nulls] as in [selfCheck], for the partner role. */
    fun measurePartner(partnerBed: DoubleArray, expectedPartner: Double, nulls: List<DoubleArray>? = null): Step {
        val s = checkNotNull(self?.takeIf { it.found }) { "selfCheck first" }
        val sw = selfWin!!
        val L = PopDsp.codeFrames(sr)
        val w = PopDsp.window(expectedPartner, sr, capture.size)
        if (w.last + 1 - w.first < 3) return Step.Failed(DspReason.CAPTURE_FAILED)
        val lo = min(sw.first, w.first)
        val hi = max(sw.last + 1, w.last + 1) + L
        if (PopDsp.runsHit(flatRuns, lo, hi)) return Step.Failed(DspReason.GLITCH)
        val a = PopDsp.measureArrival(capture, sr, partnerBed,
            nulls ?: PopDsp.nullTemplates(sessionIdHex, partnerRole, attempt, sr), expectedPartner)
        partner = a
        if (!a.found) return Step.Failed(DspReason.PARTNER_NOT_HEARD, a)
        return Step.PartnerOk(a, PopDsp.half(s.frame, a.frame, role))
    }

    companion object {
        fun pcm16Le(x: ShortArray): ByteArray {
            val b = ByteArray(2 * x.size)
            for (i in x.indices) {
                val v = x[i].toInt()
                b[2 * i] = v.toByte(); b[2 * i + 1] = (v shr 8).toByte()
            }
            return b
        }

        /** Templates on the wire are float32; the phone correlates in double. */
        fun f32ToDouble(x: FloatArray): DoubleArray = DoubleArray(x.size) { x[it].toDouble() }
    }
}
