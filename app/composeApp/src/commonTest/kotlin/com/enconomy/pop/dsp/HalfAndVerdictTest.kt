package com.enconomy.pop.dsp

import com.enconomy.pop.PopConstants
import com.enconomy.pop.toHex
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlin.test.fail

/** Contract 6.6 / 6.7 / 8.1: the per-phone procedure on every fixture; half exact, flight within 0.1 cm. */
class HalfAndVerdictTest {
    @Test fun fixturesEndToEnd() {
        for (f in DspFixtures.fixtures) {
            val halves = HashMap<Char, Int>()
            var glitched = false
            for (l in f.listeners.values) {
                val tag = "${f.name} ${l.role}"
                // web-prototype fixtures: expected_self carries ~90 ms of browser output latency
                val r = PopRound(l.capture, l.sr, l.role, f.sessionIdHex, f.attempt,
                    requireCaptureFrames = false, selfOsTolFrames = 1e9)
                val self = l.windows.first { it.kind == "self" }
                val partner = l.windows.first { it.kind == "partner" }
                val s = r.selfCheck(self.template, self.expected)
                assertIs<PopRound.Step.SelfOk>(s, tag)
                when (val p = r.measurePartner(partner.template, partner.expected)) {
                    is PopRound.Step.PartnerOk -> {
                        assertTrue(!l.glitch, "$tag expected glitch")
                        assertEquals(l.half, p.half, "$tag half")
                        halves[l.role] = p.half
                    }
                    is PopRound.Step.Failed -> {
                        assertEquals(DspReason.GLITCH, p.reason, tag)
                        assertTrue(l.glitch, "$tag unexpected glitch")
                        glitched = true
                    }
                    else -> fail("$tag $p")
                }
            }
            if (glitched) {
                assertEquals("glitch", f.verdict, f.name)
                continue
            }
            val sr = f.listeners.mapValues { it.value.sr }
            val flight = PopDsp.flightCm(halves.getValue('A'), sr.getValue('A'), halves.getValue('B'), sr.getValue('B'))
            DspFixtures.assertRel(f.flightCm!!, flight, 0.0, "${f.name} flight", 0.1)
            val verdict = when {
                flight < PopConstants.IMPOSSIBLE_CM -> "impossible_flight"
                flight < PopConstants.NEAR_CM -> "NEAR"
                else -> "NOT_NEAR"
            }
            assertEquals(f.verdict, verdict, f.name)
        }
    }

    @Test fun halfSigns() {
        // A: t_BA - t_AA ; B: t_BB - t_AB
        assertEquals(45600, PopDsp.half(1000, 46600, 'A'))
        assertEquals(45500, PopDsp.half(46600, 1100, 'B'))
        // mixed rates: 48000 / 44100, 1 ms each way -> c/2 * 2 ms
        val hA = 48000 * 950 / 1000 + 48
        val hB = 44100 * 950 / 1000 - 44   // 44.1 not exact: -0.99773 ms
        val want = 34300 / 2.0 * (hA / 48000.0 - hB / 44100.0)
        DspFixtures.assertRel(want, PopDsp.flightCm(hA, 48000, hB, 44100), 1e-12, "mixed-rate flight")
        assertTrue(PopDsp.flightCm(hA, 48000, hB, 44100) in 34.0..35.0)
    }

    @Test fun recShaIsInt16Le() {
        assertEquals("0100feff", PopRound.pcm16Le(shortArrayOf(1, -2)).toHex())
        val r = PopRound(ShortArray(10), 48000, 'A', "00".repeat(16), 0, requireCaptureFrames = false)
        assertEquals(com.enconomy.pop.sha256(ByteArray(20)).toHex(), r.recSha256.toHex())
    }
}
