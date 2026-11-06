package com.enconomy.pop

import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ClockSyncTest {
    @Test fun offsetFromOnePing() {
        // t0 = 1 s, rtt = 40 ms, server stamped 5000 ms -> offset = 5000e6 − (1e9 + 20e6)
        val o = ClockSync.best(listOf(ClockPing(1_000_000_000L, 1_040_000_000L, 5000L)))
        assertEquals(5_000_000_000L - 1_020_000_000L, o.offsetNs)
        assertEquals(40.0, o.rttMinMs)
        assertTrue(o.ok)
    }

    @Test fun keepsSmallestRtt() {
        val pings = listOf(
            ClockPing(0L, 90_000_000L, 1000L),
            ClockPing(100_000_000L, 110_000_000L, 1105L), // rtt 10 ms
            ClockPing(200_000_000L, 250_000_000L, 1300L),
        )
        val o = ClockSync.best(pings)
        assertEquals(1105L * 1_000_000L - 105_000_000L, o.offsetNs)
        assertEquals(10.0, o.rttMinMs)
        assertEquals(3, o.pings)
    }

    @Test fun roundTripServerLocal() {
        val o = ClockOffset(offsetNs = 1_790_000_000_000_000_000L - 123_456_789L, rttMinMs = 5.0, pings = 10)
        val t0Ms = 1_790_000_000_500L
        val local = o.localNs(t0Ms)
        assertEquals(t0Ms.toDouble(), o.serverMs(local), 1e-6)
        assertEquals(t0Ms * 1_000_000L - o.offsetNs, local)
    }

    @Test fun refusesSlowNetwork() {
        assertFalse(ClockSync.best(listOf(ClockPing(0L, 301_000_000L, 0L))).ok)
        assertTrue(ClockSync.best(listOf(ClockPing(0L, 300_000_000L, 0L))).ok)
    }

    @Test fun rejectsEmptyAndNegative() {
        assertFailsWith<IllegalArgumentException> { ClockSync.best(emptyList()) }
        assertFailsWith<IllegalStateException> { ClockSync.best(listOf(ClockPing(10L, 5L, 0L))) }
    }

    /** Simulated server clock ahead by D, asymmetric path; the min-rtt ping bounds the error by rtt/2. */
    @Test fun measureRecoversOffset() = runTest {
        val d = 7_654_321_000_000L // server − local, ns
        var now = 1_000_000_000L
        val up = longArrayOf(30, 5, 12, 40, 3, 8, 22, 9, 15, 50).map { it * 1_000_000L }
        val down = longArrayOf(10, 6, 4, 30, 2, 9, 1, 7, 5, 20).map { it * 1_000_000L }
        var i = 0
        val o = ClockSync.measure(n = 10, nanoTime = { now }) {
            now += up[i]
            val s = (now + d) / 1_000_000L
            now += down[i]
            i++
            s
        }
        assertEquals(10, o.pings)
        assertEquals(5.0, o.rttMinMs) // ping 4: 3 + 2 ms
        // truth offset is d; error ≤ rtt/2 + 1 ms (server_ms truncation)
        assertTrue(kotlin.math.abs(o.offsetNs - d) <= 2_500_000L + 1_000_000L, "err ${(o.offsetNs - d) / 1e6} ms")
    }

    @Test fun measureSkipsFailedPings() = runTest {
        var now = 0L
        var k = 0
        val o = ClockSync.measure(n = 4, nanoTime = { now += 1_000_000L; now }) {
            if (k++ % 2 == 0) error("net") else 42L
        }
        assertEquals(2, o.pings)
        assertFailsWith<IllegalStateException> { ClockSync.measure(n = 3, nanoTime = { 0L }) { error("down") } }
    }
}
