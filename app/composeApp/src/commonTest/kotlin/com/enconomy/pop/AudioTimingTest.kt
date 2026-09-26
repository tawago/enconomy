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

    @Test fun iosPresentationIsRenderTimePlusOutputLatencyOnly() {
        // iPhone X, VideoRecording mode: outputLatency 382 frames, IO buffer 1024 frames (not added)
        val outLat = 382.0 / sr
        assertEquals(1_000_000_000L + 7_958_333L, AudioTiming.presentationNs(1_000_000_000L, outLat))
        // role A: the player's render IO time of track frame 0 is the scheduled play call (t0 − primer)
        val plan = RunPlan('A', sr, 0L, t0Ns)
        val nano = AudioTiming.presentationNs(plan.playCallNs, outLat)
        val f0 = plan.captureStartNs
        val expected = AudioTiming.frameOf(AudioTiming.playOnsetNs(nano, 0L, sr), f0, sr)
        assertEquals(24000.0 + 382.0, expected, 0.01)
    }

    @Test fun iphoneXTranscriptsWithinDelta() {
        // real v2 transcripts (sessions 5aca0936 A, 7a3c1d25 B, a5addf50 B, da5b02ea A): signed play_nano_time had
        // + IOBufferDuration (1024 frames). Removing it: self_os_delta −1013/−1014/−1012/−1016 -> 11/10/12/8.
        val io = kotlin.math.round(1024.0 / sr * 1e9).toLong()
        data class T(val pos: Long, val nano: Long, val f0: Long, val aSelf: Int, val oldDelta: Int, val newDelta: Int)
        val runs = listOf(
            T(116703, 7311475312249, 7308814705228, 24393, -1013, 11),
            T(70898, 6199887484624, 6197231154978, 69992, -1014, 10),
            T(71680, 7333431213291, 7330758581520, 69994, -1012, 12),
            T(117855, 6178988153041, 6176303574874, 24389, -1016, 8),
        )
        for (t in runs) {
            val old = kotlin.math.round(AudioTiming.frameOf(AudioTiming.playOnsetNs(t.nano, t.pos, sr), t.f0, sr)).toInt()
            assertEquals(t.oldDelta, t.aSelf - old)
            val new = kotlin.math.round(AudioTiming.frameOf(AudioTiming.playOnsetNs(t.nano - io, t.pos, sr), t.f0, sr)).toInt()
            assertEquals(t.newDelta, t.aSelf - new)
            assertTrue(kotlin.math.abs(t.aSelf - new) <= 96)
        }
    }

    @Test fun playStampsDropStaleAndPickMedianOnset() {
        val ps = PlayStamps(sr)
        assertEquals(null, ps.pick())
        val onset = t0Ns
        fun nanoAt(pos: Long, errNs: Long = 0) = onset + (pos - 14400) * 1_000_000_000L / sr + errNs
        assertTrue(!ps.add(0L, nanoAt(0)))                 // no position yet
        assertTrue(ps.add(14880L, nanoAt(14880, 3_000_000))) // startup outlier, +3 ms
        assertTrue(ps.add(15360L, nanoAt(15360)))
        assertTrue(!ps.add(15360L, nanoAt(15360) + 5_000_000)) // same position: stale
        assertTrue(!ps.add(15840L, nanoAt(15360) - 1))          // time went back: stale
        assertTrue(ps.add(15840L, nanoAt(15840)))
        assertTrue(ps.add(16320L, nanoAt(16320, -1_000_000)))
        assertTrue(ps.add(16800L, nanoAt(16800)))
        assertEquals(5, ps.size)
        val p = ps.pick()!!
        assertEquals(onset.toDouble(), AudioTiming.playOnsetNs(p.second, p.first, sr), 1.0)
        assertEquals(4000.0, ps.spreadUs(), 1e-3)
    }

    @Test fun extraMetaInMeta() {
        val c = Capture(
            pcm = ShortArray(4), sr = sr, recFrame0NanoTime = 0L, playFramePosition = 1L, playNanoTime = 1L,
            tsSource = "audiotimestamp", recTsSource = "audiotimestamp", outputLatencyMs = 8.0, micSource = "m",
            effectsOff = emptyList(), playLateMs = 0.0, recTsSpreadUs = 0.0, framesRecorded = 4L, captureStartFrame = 0L,
            trackDrained = true, extraMeta = mapOf("io_buffer_ms" to 21.25),
        )
        assertEquals("21.25", c.meta()["io_buffer_ms"].toString())
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
