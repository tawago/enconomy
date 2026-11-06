package com.enconomy.pop

import kotlinx.serialization.EncodeDefault
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.Serializable
import kotlin.math.abs
import kotlin.math.roundToLong

/**
 * Enrollment calibration (server pop/calibration.py): the audio check runs [PopConstants.CAL_N] times, each
 * self offset (same self_os_delta math as a v2 run, [SelfOffset]) in µs; the median is the device's cal_us.
 * Rejected when max − min > CAL_SPREAD_MAX_US or the median is outside −CAL_NEG_CLAMP_US..CAL_MAX_US;
 * a median in [−CAL_NEG_CLAMP_US, 0) becomes 0. The run's self check is then
 * |self_os_delta − cal_frames| ≤ SELF_OS_TOL_MS, exact as the server: |d·1e6 − cal_us·sr| ≤ tol·1000·sr.
 * Circuit inputs and SBcred3 do not change.
 */
@OptIn(ExperimentalSerializationApi::class)
@Serializable
data class CalibrationReq(
    val cal_us: Long,
    val sample_rate: Int,
    val route: String,
    val backend: String,
    @EncodeDefault(EncodeDefault.Mode.NEVER) val samples_us: List<Long>? = null,
)

@Serializable
data class CalibrationResp(
    val cal_us: Long,
    val sample_rate: Int? = null,
    val route: String? = null,
    val backend: String? = null,
    val at: String? = null,
)

@Serializable data class RecalibrateReq(val calibration: CalibrationReq)
@Serializable data class RecalibrateResp(val device_id: String, val calibration: CalibrationResp? = null)

class CalibrationException(msg: String) : Exception(msg)

object Calibration {
    /** CAL_N offsets in µs -> cal_us; throws [CalibrationException] on spread / range. */
    fun fromSamples(samplesUs: List<Long>): Long {
        if (samplesUs.size != PopConstants.CAL_N) throw CalibrationException("need ${PopConstants.CAL_N} samples, got ${samplesUs.size}")
        val s = samplesUs.sorted()
        val spread = s.last() - s.first()
        if (spread > PopConstants.CAL_SPREAD_MAX_US) throw CalibrationException("spread $spread µs > ${PopConstants.CAL_SPREAD_MAX_US}")
        val med = s[s.size / 2]
        if (med < -PopConstants.CAL_NEG_CLAMP_US || med > PopConstants.CAL_MAX_US) {
            throw CalibrationException("median $med µs outside -${PopConstants.CAL_NEG_CLAMP_US}..${PopConstants.CAL_MAX_US}")
        }
        return maxOf(0L, med)
    }

    fun framesToUs(frames: Int, sr: Int): Long = (frames.toDouble() * 1_000_000.0 / sr).roundToLong()

    /** |d − cal_frames| ≤ tol, exact integers (server verdict.self_os_ok). */
    fun selfOsOk(deltaFrames: Int, sr: Int, calUs: Long, tolMs: Int = PopConstants.SELF_OS_TOL_MS): Boolean =
        abs(deltaFrames.toLong() * 1_000_000L - calUs * sr) <= tolMs.toLong() * 1000L * sr

    /** Offset left after calibration, µs (meta). */
    fun calibratedUs(deltaFrames: Int, sr: Int, calUs: Long): Long = framesToUs(deltaFrames, sr) - calUs

    /** What cal_sig_b64 signs at enroll (server calibration.message). */
    fun message(nonceHex: String, c: CalibrationReq): ByteArray =
        listOf("pop-cal-v1", nonceHex.lowercase(), c.cal_us.toString(), c.sample_rate.toString(), c.route, c.backend)
            .joinToString("\n").encodeToByteArray()

    /** "12.35 ms" */
    fun text(us: Long): String = "${kotlin.math.round(us / 10.0) / 100} ms"

    // ---- local copy (Prefs), the server's value wins in a session view ----
    fun save(c: CalibrationReq?) {
        Prefs.set("cal.us", c?.cal_us?.toString())
        Prefs.set("cal.sr", c?.sample_rate?.toString())
        Prefs.set("cal.route", c?.route)
        Prefs.set("cal.backend", c?.backend)
        Prefs.set("cal.samples", c?.samples_us?.joinToString(","))
    }

    fun load(): CalibrationReq? {
        val us = Prefs.get("cal.us")?.toLongOrNull() ?: return null
        return CalibrationReq(us, Prefs.get("cal.sr")?.toIntOrNull() ?: 0, Prefs.get("cal.route") ?: "", Prefs.get("cal.backend") ?: "",
            Prefs.get("cal.samples")?.split(",")?.mapNotNull { it.toLongOrNull() })
    }
}
