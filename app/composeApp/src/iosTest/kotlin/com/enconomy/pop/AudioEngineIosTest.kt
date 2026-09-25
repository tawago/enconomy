package com.enconomy.pop

import platform.AVFAudio.AVAudioTime
import platform.QuartzCore.CACurrentMediaTime
import kotlin.math.abs
import kotlin.math.round
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AudioEngineIosTest {
    @Test
    fun hostTicksRoundTrip() {
        for ((n, d) in listOf(125L to 3L, 1L to 1L)) {
            for (ns in listOf(0L, 1L, 41L, 42L, 1_000_000_007L, 86_400_000_000_000L * 30)) {
                val t = nsToHostTicks(ns, n, d)
                assertTrue(abs(hostTicksToNs(t, n, d) - ns) <= n / d, "ns $ns via $n/$d")
            }
        }
        assertEquals(1_000_000_000L, hostTicksToNs(24_000_000L, 125, 3)) // 24 MHz
        assertEquals(24_000_000L, nsToHostTicks(1_000_000_000L, 125, 3))
        // year of uptime at 24 MHz, no overflow
        val year = 24_000_000L * 86_400 * 365
        assertEquals(year / 3 * 125, hostTicksToNs(year, 125, 3))
    }

    /** CACurrentMediaTime is mach_absolute_time in seconds, the AVAudioTime host clock. */
    @Test
    fun hostClockIsMonoNanos() {
        val a = monoNanos()
        val h = round(CACurrentMediaTime() * 1e9).toLong()
        val b = monoNanos()
        assertTrue(h in (a - 10_000)..(b + 10_000), "host $h vs mono [$a, $b]")
        val t = HostClock.toHost(a)
        assertTrue(abs(HostClock.toNs(t) - a) < 100)
        assertTrue(abs(AVAudioTime.secondsForHostTime(t) * 1e9 - a) < 1_000, "AVAudioTime disagrees")
    }

    @Test
    fun pcm16LikeAndroid() {
        assertEquals(0, f32ToPcm16(0f).toInt())
        assertEquals(16384, f32ToPcm16(0.5f).toInt())
        assertEquals(-16384, f32ToPcm16(-0.5f).toInt())
        assertEquals(32767, f32ToPcm16(1f).toInt())
        assertEquals(-32768, f32ToPcm16(-1f).toInt())
        assertEquals(32767, f32ToPcm16(3f).toInt())
        assertEquals(-32768, f32ToPcm16(-3f).toInt())
        assertEquals(1, f32ToPcm16(1f / 32768).toInt())
        assertEquals(0, f32ToPcm16(Float.NaN).toInt())
    }

    @Test
    fun sampleRateRange() {
        assertEquals(48000, sessionRate(48000.0))
        assertEquals(44100, sessionRate(44100.0))
        assertNull(sessionRate(16000.0))
        assertNull(sessionRate(192000.0))
    }
}
