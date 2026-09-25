package com.enconomy.pop

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlin.test.Test
import kotlin.test.assertEquals

class PopConstantsTest {
    // verbatim json.dumps(pop.constants.table()) + the extra /v1/config keys
    private val server = """{"proto": "pop-v1", "sr_min": 36000, "sr_max": 96000, "code_s": 0.25, "band_hz": [2000, 18000], "fade_s": 0.005, "target_rms": 0.15, "max_peak": 0.95, "primer_s": 0.3, "lead_s": 0.5, "capture_s": 2.5, "a_play_s": 0.0, "b_play_s": 0.95, "search_pre_s": 0.15, "search_post_s": 0.25, "segment_margin_s": 0.1, "n_null": 64, "null_p": 0.0001, "null_p_safety": 3.0, "floor_score": 0.05, "half_frac": 0.5, "half_lookahead_s": 0.005, "flat_run_min_s": 0.008, "impossible_cm": -20, "near_cm": 60, "speed_of_sound_cm_s": 34300, "self_os_tol_ms": 50, "transcript_deadline_s": 20, "max_attempts": 2, "allow_unattested": false, "gain_db": 0.0, "upload_recordings": true}"""

    private fun cfg() = popJson.parseToJsonElement(server).jsonObject

    @Test fun matchesServerTable() = assertEquals(emptyList(), PopConstants.mismatches(cfg()))

    @Test fun flagsChangedAndMissing() {
        val c = cfg().toMutableMap()
        c["near_cm"] = JsonPrimitive(61)
        c["proto"] = JsonPrimitive("pop-v2")
        c.remove("band_hz")
        assertEquals(setOf("near_cm", "proto", "band_hz"), PopConstants.mismatches(JsonObject(c)).toSet())
    }
}
