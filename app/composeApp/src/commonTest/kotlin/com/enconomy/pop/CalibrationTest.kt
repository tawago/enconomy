package com.enconomy.pop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Same vectors as server tests/test_calibration.py (pop/calibration.py is the reference). */
class CalibrationTest {
    @Test fun medianRule() {
        assertEquals(20000L, Calibration.fromSamples(listOf(20000, 20100, 19900, 20050, 19950)))
        assertEquals(0L, Calibration.fromSamples(listOf(-400, -500, -600, -450, -550)))       // small negative clamps
        assertEquals(0L, Calibration.fromSamples(listOf(-2000, -1900, -2100, -1950, -2050)))  // exactly -2 ms
        assertEquals(50000L, Calibration.fromSamples(listOf(50000, 49900, 50100, 49950, 50050)))
    }

    @Test fun rejects() {
        assertFailsWith<CalibrationException> { Calibration.fromSamples(listOf(0, 0, 0, 0, 1001)) }        // spread
        assertFailsWith<CalibrationException> { Calibration.fromSamples(listOf(-2100, -2050, -2001, -2200, -2150)) }
        assertFailsWith<CalibrationException> { Calibration.fromSamples(listOf(50001, 50001, 50001, 50001, 50001)) }
        assertFailsWith<CalibrationException> { Calibration.fromSamples(listOf(1, 2, 3, 4)) }
    }

    @Test fun spreadBoundaryPasses() = assertEquals(500L, Calibration.fromSamples(listOf(0, 1000, 500, 400, 600)))

    @Test fun selfOsOkMatchesServer() {
        val sr = 48000
        assertTrue(Calibration.selfOsOk(2400, sr, 0)); assertFalse(Calibration.selfOsOk(2401, sr, 0))
        assertTrue(Calibration.selfOsOk(1440 + 2400, sr, 30000)); assertFalse(Calibration.selfOsOk(1440 + 2401, sr, 30000))
        assertTrue(Calibration.selfOsOk(1440 - 2400, sr, 30000)); assertFalse(Calibration.selfOsOk(1440 - 2401, sr, 30000))
        assertTrue(Calibration.selfOsOk(1323 + 2205, 44100, 30000)); assertFalse(Calibration.selfOsOk(1323 + 2206, 44100, 30000))
    }

    @Test fun framesToUs() {
        assertEquals(20000L, Calibration.framesToUs(960, 48000))
        assertEquals(998L, Calibration.framesToUs(44, 44100)) // 997.7
        assertEquals(-2500L, Calibration.calibratedUs(960, 48000, 22500))
    }

    @Test fun signedMessageLayout() {
        val c = CalibrationReq(12000, 48000, "speaker", "aaudio/unprocessed", listOf(1, 2, 3, 4, 5))
        assertEquals("pop-cal-v1\nabcd\n12000\n48000\nspeaker\naaudio/unprocessed", Calibration.message("ABCD", c).decodeToString())
    }

    @Test fun enrollBodyOmitsCalibrationWhenAbsent() {
        val base = EnrollReq("n", "d", "p", "x", "m", "tee", null)
        val plain = popJson.encodeToString(EnrollReq.serializer(), base)
        assertFalse("calibration" in plain || "cal_sig_b64" in plain)
        val c = CalibrationReq(12000, 48000, "speaker", "aaudio", null)
        val s = popJson.encodeToString(EnrollReq.serializer(), base.copy(calibration = c, cal_sig_b64 = "AA=="))
        assertTrue("\"calibration\":{\"cal_us\":12000,\"sample_rate\":48000,\"route\":\"speaker\",\"backend\":\"aaudio\"}" in s, s)
        assertTrue("\"cal_sig_b64\":\"AA==\"" in s)
    }
}
