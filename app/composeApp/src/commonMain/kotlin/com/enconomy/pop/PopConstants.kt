package com.enconomy.pop

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlin.math.abs

/** Contract §6.1. Same values as server pop/constants.py; checked against GET /v1/config at startup. */
object PopConstants {
    const val PROTO = "pop-v1"
    const val SR_MIN = 36000
    const val SR_MAX = 96000
    const val CODE_S = 0.25
    val BAND_HZ = doubleArrayOf(2000.0, 18000.0)
    const val FADE_S = 0.005
    const val TARGET_RMS = 0.15
    const val MAX_PEAK = 0.95
    const val PRIMER_S = 0.3
    const val LEAD_S = 0.5
    const val CAPTURE_S = 2.5
    const val A_PLAY_S = 0.0
    const val B_PLAY_S = 0.95
    const val SEARCH_PRE_S = 0.150
    const val SEARCH_POST_S = 0.250
    const val SEGMENT_MARGIN_S = 0.1
    const val N_NULL = 64
    const val NULL_P = 1e-4
    const val NULL_P_SAFETY = 3.0
    const val FLOOR_SCORE = 0.05
    const val HALF_FRAC = 0.5
    const val HALF_LOOKAHEAD_S = 0.005
    const val FLAT_RUN_MIN_S = 0.008
    const val IMPOSSIBLE_CM = -20
    const val NEAR_CM = 60
    const val SPEED_OF_SOUND_CM_S = 34300
    const val SELF_OS_TOL_MS = 50
    const val TRANSCRIPT_DEADLINE_S = 20
    const val MAX_ATTEMPTS = 2

    /** Lowercase keys, as /v1/config sends them. */
    val table: Map<String, Any> = mapOf(
        "proto" to PROTO, "sr_min" to SR_MIN, "sr_max" to SR_MAX, "code_s" to CODE_S,
        "band_hz" to BAND_HZ.toList(), "fade_s" to FADE_S, "target_rms" to TARGET_RMS, "max_peak" to MAX_PEAK,
        "primer_s" to PRIMER_S, "lead_s" to LEAD_S, "capture_s" to CAPTURE_S, "a_play_s" to A_PLAY_S,
        "b_play_s" to B_PLAY_S, "search_pre_s" to SEARCH_PRE_S, "search_post_s" to SEARCH_POST_S,
        "segment_margin_s" to SEGMENT_MARGIN_S, "n_null" to N_NULL, "null_p" to NULL_P,
        "null_p_safety" to NULL_P_SAFETY, "floor_score" to FLOOR_SCORE, "half_frac" to HALF_FRAC,
        "half_lookahead_s" to HALF_LOOKAHEAD_S, "flat_run_min_s" to FLAT_RUN_MIN_S,
        "impossible_cm" to IMPOSSIBLE_CM, "near_cm" to NEAR_CM, "speed_of_sound_cm_s" to SPEED_OF_SOUND_CM_S,
        "self_os_tol_ms" to SELF_OS_TOL_MS, "transcript_deadline_s" to TRANSCRIPT_DEADLINE_S,
        "max_attempts" to MAX_ATTEMPTS,
    )

    /** Keys that differ from [cfg] (missing counts). Extra server keys are ignored. Empty = ok. */
    fun mismatches(cfg: JsonObject): List<String> = table.filter { (k, v) -> !same(v, cfg[k]) }.keys.toList()

    private fun same(v: Any, j: JsonElement?): Boolean = when (v) {
        is String -> (j as? JsonPrimitive)?.takeIf { it.isString }?.content == v
        is Number -> (j as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull?.let { near(it, v.toDouble()) } == true
        is List<*> -> j is JsonArray && j.size == v.size && v.indices.all { same(v[it]!!, j[it]) }
        else -> false
    }

    private fun near(a: Double, b: Double) = a == b || abs(a - b) <= 1e-12 * maxOf(abs(a), abs(b))
}
