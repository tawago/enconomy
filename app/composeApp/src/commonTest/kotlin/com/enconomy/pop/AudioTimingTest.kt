package com.enconomy.pop

import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class AudioTimingTest {
    private val sr = 48000
    private val t0Ns = 50_000_000_000L

    @Test fun planA() {
        val p = RunPlan('A', sr, 0L, t0Ns)
        assertEquals(t0Ns - 1_000_000_000L, p.recStartNs)
        assertEquals(t0Ns - 300_000_000L, p.playCallNs) // sound at t0
        assertEquals(t0Ns + 2_000_000_000L, p.stopNs)
        assertEquals(t0Ns - 500_000_000L, p.captureStartNs)
        assertEquals(14400, p.primerFrames)
        assertEquals(120000, p.captureFrames)
    }

    @Test fun planB() {
        val p = RunPlan('B', sr, 0L, t0Ns)
        assertEquals(t0Ns + 650_000_000L, p.playCallNs) // sound at t0 + 0.95
        // B listens to A at t0: capture frame 0 = t0 − 0.5 s -> 0.5·sr
        assertEquals(24000.0, p.expectedPartner(t0Ns - 500_000_000L), 1e-9)
        // A listens to B at t0 + 0.95 -> 1.45·sr
        assertEquals(69600.0, RunPlan('A', sr, 0L, t0Ns).expectedPartner(t0Ns - 500_000_000L), 1e-9)
        assertFailsWith<IllegalArgumentException> { RunPlan('C', sr, 0L, t0Ns) }
    }

    @Test fun planFromClock() {
        val c = ClockOffset(offsetNs = 1_000_000_000_000L, rttMinMs = 3.0, pings = 10)
        val p = RunPlan.of("B", 44100, 5_000_000L, c)
        assertEquals(5_000_000L * 1_000_000L - 1_000_000_000_000L, p.t0Ns)
        assertEquals(13230, p.primerFrames)
        assertEquals(110250, p.captureFrames)
    }

    @Test fun osTimestampsToExpectedSelf() {
        // mic: frame 24000 captured at t0 − 0.5 s  -> frame 0 at t0 − 1.0 s
        val recF0 = AudioTiming.recFrame0Ns(t0Ns - 500_000_000L, 24000L, sr)
        assertEquals((t0Ns - 1_000_000_000L).toDouble(), recF0, 1e-3)
        val start = AudioTiming.captureStartFrame(t0Ns - 500_000_000L, recF0, sr)
        assertEquals(24000L, start)
        val f0 = kotlin.math.round(recF0 + start * 1e9 / sr).toLong()
        assertEquals(t0Ns - 500_000_000L, f0)

        // speaker: track frame 20000 out at t0 + 5600/48000 s -> onset (frame 14400) exactly at t0 + 2 ms
        val onsetNs = t0Ns + 2_000_000L
        val tsNano = onsetNs + (20000 - 14400) * 1_000_000_000L / sr
        val onset = AudioTiming.playOnsetNs(tsNano, 20000L, sr)
        assertEquals(onsetNs.toDouble(), onset, 1.0)
        // expected_self = 0.5 s + 2 ms
        assertEquals(24096.0, AudioTiming.frameOf(onset, f0, sr), 1e-3)
    }

    @Test fun captureStartRoundsToNearest() {
        val period = 1e9 / sr
        val recF0 = 0.0
        assertEquals(10L, AudioTiming.captureStartFrame((10 * period + 0.4 * period).toLong(), recF0, sr))
        assertEquals(11L, AudioTiming.captureStartFrame((10 * period + 0.6 * period).toLong(), recF0, sr))
    }

    @Test fun captureExpectedFromFields() {
        val sr = 44100
        val c = Capture(
            pcm = ShortArray(AudioTiming.captureFrames(sr)), sr = sr, recFrame0NanoTime = 1_000_000_000L,
            playFramePosition = 13230L, playNanoTime = 1_600_000_000L, tsSource = "audiotimestamp",
            recTsSource = "audiotimestamp", outputLatencyMs = 12.0, micSource = "unprocessed", effectsOff = listOf("agc"),
            playLateMs = 0.0, recTsSpreadUs = 20.0, framesRecorded = 150000L, captureStartFrame = 22050L, trackDrained = true,
        )
        // onset at ts (framePosition == primer) -> 0.6 s after capture frame 0
        assertEquals(0.6 * sr, c.expectedSelf(), 1e-6)
        val plan = RunPlan('B', sr, 0L, 1_500_000_000L)
        assertEquals(0.5 * sr, c.expectedPartner(plan), 1e-6)
        val m = c.meta()
        assertEquals("\"audiotimestamp\"", m["ts_source"].toString())
        assertEquals("12.0", m["output_latency_ms"].toString())
        assertEquals(32, c.recSha256.size)
    }

    @Test fun recShaIsInt16Le() {
        val x = shortArrayOf(1, -2, 32767, -32768)
        assertContentEquals(
            byteArrayOf(1, 0, 0xfe.toByte(), 0xff.toByte(), 0xff.toByte(), 0x7f, 0, 0x80.toByte()),
            AudioTiming.pcm16Le(x),
        )
        assertEquals("23d04b5c88ae1fb6243c38676a30b686e9b9e4414133d9933319fdbf9d4a05bb", AudioTiming.recSha256(x).toHex())
    }

    @Test fun pcmWireDecode() {
        val sr = 36000
        val n = 9000
        val b = ByteArray(4 * n)
        "0000003f000080bf0000803e".hexToBytes().copyInto(b)
        val f = Pcm(b.toB64(), n).decodeF32(sr)
        assertEquals(n, f.size)
        assertEquals(0.5f, f[0]); assertEquals(-1.0f, f[1]); assertEquals(0.25f, f[2]); assertEquals(0f, f[3])
        assertEquals(0.25, Pcm(b.toB64(), n).decodeF64(sr)[2])
        val e1 = assertFailsWith<AudioException> { Pcm(b.toB64(), n + 1).decodeF32(sr) }
        assertEquals("capture_failed", e1.reason)
        assertFailsWith<AudioException> { Pcm(b.toB64(), n).decodeF32(48000) }
    }

    @Test fun medianOddEven() {
        assertEquals(2.0, AudioTiming.median(listOf(3.0, 1.0, 2.0)))
        assertEquals(2.5, AudioTiming.median(listOf(4.0, 1.0, 2.0, 3.0)))
        assertTrue(AudioTiming.median(listOf(-1.0)) < 0)
    }
}
