package com.enconomy.pop.dsp

import com.enconomy.pop.PopConstants
import kotlin.math.abs

/**
 * POPT v2 steps for one phone and one attempt (docs/pop-transcript-v2.md §3). Same order as [PopRound]:
 * [selfCheck], then the caller commits rec_root and gets the partner code, then [measurePartner].
 *
 *   p_self    = round(expected_self + cal_frames)   a_self = earliest pass, own code, [p_self − WPRE, p_self + WPOST)
 *   p_partner = round(expected_partner)    a_partner = same with the partner code around p_partner
 *   self_os_delta = a_self − p_self, |·| ≤ selfOsTolMs (|d|·1000 ≤ tol·sr, as the server for v2).
 *   cal_frames = calUs·sr/1e6 (enrollment calibration, 0 = none) is folded into p_self before signing, so the
 *   signed self_os_delta is the residual after calibration and the circuit's |self_os_delta| ≤ delta can hold
 *   on a device with a stable audio latency.
 *   half = A: a_partner − a_self, B: a_self − a_partner
 *
 * Glitch (flat runs) and capture-length checks are the v1 ones. The v1 null-bar rule is not run.
 * [provable] = what the option A circuit also needs: |self_os_delta| ≤ delta (2 ms), the FIR margins
 * p_self − delta − 31 ≥ 0 and a_partner − 31 ≥ 0. The server verdict does not depend on it.
 */
class PopRound2(
    val capture: ShortArray,
    val rate: Popt2Rate,
    val role: Char,
    val selfOsTolMs: Int = PopConstants.SELF_OS_TOL_MS,
    requireCaptureFrames: Boolean = true,
    /** Enrollment calibration, µs (0 = none): folded into p_self (p_self = round(expected_self + cal_frames)). */
    val calUs: Long = 0,
) {
    sealed class Step {
        data class Failed(val reason: String, val arrival: Arrival2? = null) : Step()
        data class SelfOk(val aSelf: Int, val pSelf: Int, val selfOsDelta: Int) : Step()
        data class PartnerOk(val aPartner: Int, val pPartner: Int, val half: Int) : Step()
    }

    val sr: Int get() = rate.sr
    val captureOk: Boolean = !requireCaptureFrames || capture.size == pyRound(PopConstants.CAPTURE_S * rate.sr)
    val flatRuns: List<IntRange> by lazy { PopDsp.flatRuns(capture, rate.sr) }

    var self: Arrival2? = null
        private set
    var partner: Arrival2? = null
        private set
    var pSelf: Int? = null
        private set
    var pPartner: Int? = null
        private set

    fun window(p: Int): IntRange = (p - rate.wpre) until (p + rate.wpost)

    fun selfCheck(own: Popt2Code, expectedSelf: Double): Step {
        if (!captureOk || own.n != rate.L) return Step.Failed(DspReason.CAPTURE_FAILED)
        val p = pyRound(expectedSelf + calUs * rate.sr / 1e6)
        pSelf = p
        val w = window(p)
        if (w.first < 0 || w.last + rate.L > capture.size) return Step.Failed(DspReason.CAPTURE_FAILED)
        if (PopDsp.runsHit(flatRuns, w.first, w.last + 1 + rate.L)) return Step.Failed(DspReason.GLITCH)
        val a = Popt2Rule.earliest(capture, own, w.first, w.last + 1, rate)
        self = a
        val f = a.frame ?: return Step.Failed(DspReason.SELF_NOT_HEARD, a)
        val d = f - p
        if (!selfOsOk(d)) return Step.Failed(DspReason.SELF_TIMESTAMP_MISMATCH, a)
        return Step.SelfOk(f, p, d)
    }

    fun measurePartner(partnerCode: Popt2Code, expectedPartner: Double): Step {
        val s = checkNotNull(self?.frame) { "selfCheck first" }
        if (partnerCode.n != rate.L) return Step.Failed(DspReason.CAPTURE_FAILED)
        val p = pyRound(expectedPartner)
        pPartner = p
        val w = window(p)
        if (w.first < 0 || w.last + rate.L > capture.size) return Step.Failed(DspReason.CAPTURE_FAILED)
        val sw = window(pSelf!!)
        if (PopDsp.runsHit(flatRuns, minOf(sw.first, w.first), maxOf(sw.last, w.last) + 1 + rate.L)) {
            return Step.Failed(DspReason.GLITCH)
        }
        val a = Popt2Rule.earliest(capture, partnerCode, w.first, w.last + 1, rate)
        partner = a
        val f = a.frame ?: return Step.Failed(DspReason.PARTNER_NOT_HEARD, a)
        return Step.PartnerOk(f, p, if (role == 'A') f - s else s - f)
    }

    /** d is already calibrated (cal folded into p_self): |d| ≤ tol. */
    fun selfOsOk(d: Int): Boolean = com.enconomy.pop.Calibration.selfOsOk(d, rate.sr, 0, selfOsTolMs)

    /** Option A provability of the signed values (§3.7 of the port spec); null before both arrivals. */
    val provable: Boolean?
        get() {
            val a = self?.frame ?: return null
            val ap = partner?.frame ?: return null
            val p = pSelf!!
            val pp = pPartner!!
            return abs(a - p) <= rate.delta && p - rate.delta - Popt2Rule.HM >= 0 && ap - Popt2Rule.HM >= 0 &&
                ap in (pp - rate.wpre)..(pp + rate.wpost)
        }
}
