package com.enconomy.pop

import android.os.Process
import android.util.Log
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * Backend "aaudio": one opened AAudio duplex (pop_aaudio.cpp), LOW_LATENCY, EXCLUSIVE requested (MMAP).
 * Same contract as the Java path: the input stream starts at plan.recStartNs and keeps the whole recording,
 * the output stream starts at plan.playCallNs and plays PRIMER zeros ‖ play from its first callback.
 *
 * Times come from AAudioStream_getTimestamp(CLOCK_MONOTONIC), framePosition taken relative to each stream's
 * first callback frame (= index 0 of rec / of primer ‖ play):
 *   mic frame 0 = median over input readings of nanoTime − framePosition/sr (after 0.5 s of recording),
 *   play = the output reading with the median onset among the advancing ones read while playing (PlayStamps).
 */
internal class AAudioSession(private val h: Long, private val sr: Int, private val micSource: String) {
    private val info = AAudioNative.info(h)
    private var closed = false

    val exclusive: Boolean get() = info[0] == AAudioNative.SHARING_EXCLUSIVE && info[1] == AAudioNative.SHARING_EXCLUSIVE

    private fun sharing(v: Int) = if (v == AAudioNative.SHARING_EXCLUSIVE) "exclusive" else "shared"
    private fun mmap(v: Int) = when (v) { 1 -> "mmap"; 0 -> "legacy"; else -> "mmap?" }

    /** e.g. "aaudio out exclusive/mmap in exclusive/mmap". */
    fun describe(): String =
        if (info[0] == info[1] && info[2] == info[3]) "aaudio ${sharing(info[0])} ${mmap(info[2])}"
        else "aaudio out ${sharing(info[0])}/${mmap(info[2])} in ${sharing(info[1])}/${mmap(info[3])}"

    fun record(plan: RunPlan, outputLatencyMs: Double?, route: AudioRoute?): Capture {
        val stamps = PlayStamps(sr)
        val estimates = ArrayList<Double>()
        val latOut = ArrayList<Double>()
        val latIn = ArrayList<Double>()
        val halfSec = sr / 2L

        val called = AtomicLong(0L)
        val startErr = AtomicInteger(0)
        val starter = Thread({
            Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_AUDIO)
            sleepUntil(plan.playCallNs)
            called.set(System.nanoTime())
            startErr.set(AAudioNative.startOut(h))
        }, "pop-play").apply { priority = Thread.MAX_PRIORITY }

        sleepUntil(plan.recStartNs)
        val si = AAudioNative.startIn(h)
        if (si != 0) throw AudioException("capture_failed", "AAudio input start = $si")
        starter.start()
        val hardStop = plan.stopNs + 1_500_000_000L
        var lastInTs = 0L
        var st = AAudioNative.status(h)
        try {
            while (true) {
                Thread.sleep(10)
                val now = System.nanoTime()
                st = AAudioNative.status(h)
                val outPos = st[0]; val playFrames = st[1]; val recPos = st[2]
                if (st[8] != 0L || st[9] != 0L) throw AudioException("capture_failed", "AAudio stream error out=${st[8]} in=${st[9]}")
                if (startErr.get() != 0) throw AudioException("capture_failed", "AAudio output start = ${startErr.get()}")
                if (recPos >= halfSec && recPos - lastInTs >= sr / 20) {
                    val ts = AAudioNative.timestamp(h, false)
                    if (ts[0] == 1L && ts[1] > 0) {
                        lastInTs = recPos
                        estimates += AudioTiming.recFrame0Ns(ts[2], ts[1], sr)
                    }
                }
                if (called.get() != 0L && outPos in 1 until playFrames) {
                    val ts = AAudioNative.timestamp(h, true)
                    if (ts[0] == 1L) stamps.add(ts[1], ts[2])
                    val l = AAudioNative.latency(h)
                    if (l[0] >= 0) latOut += l[0]
                    if (l[1] >= 0) latIn += l[1]
                }
                if (now >= plan.stopNs + 100_000_000L && outPos >= playFrames && estimates.isNotEmpty()) {
                    val need = AudioTiming.captureStartFrame(plan.captureStartNs, AudioTiming.median(estimates), sr) + plan.captureFrames
                    if (recPos >= need || now >= hardStop) break
                }
                if (now >= hardStop + 1_000_000_000L) break
            }
        } finally {
            AAudioNative.stop(h)
            starter.join(3000)
        }
        st = AAudioNative.status(h)
        val calledNs = called.get()
        if (calledNs == 0L) throw AudioException("capture_failed", "output never started")
        if (estimates.isEmpty()) throw AudioException("capture_failed", "no AAudio input timestamp")
        val pos = st[2]
        val f0 = AudioTiming.median(estimates)
        val spreadUs = if (estimates.size > 1) (estimates.max() - estimates.min()) / 1e3 else 0.0
        val start = AudioTiming.captureStartFrame(plan.captureStartNs, f0, sr)
        val frames = plan.captureFrames
        if (start < 0 || start + frames > pos) {
            throw AudioException("capture_failed", "capture [$start, ${start + frames}) outside recorded [0, $pos)")
        }
        val pcm = AAudioNative.capture(h, start.toInt(), frames) ?: throw AudioException("capture_failed", "capture copy")
        val frame0 = kotlin.math.round(f0 + start * 1e9 / sr).toLong()

        val ts = stamps.pick()
        val (pos0, nano0, src) = if (ts != null) Triple(ts.first, ts.second, "audiotimestamp")
        else Triple(0L, calledNs + kotlin.math.round((outputLatencyMs ?: 0.0) * 1e6).toLong(), "fallback")
        val lateMs = maxOf(0.0, (calledNs - plan.playCallNs) / 1e6)
        Log.i("PopAudio", "aaudio ${describe()} src=$micSource spread=${"%.1f".format(spreadUs)}us play ts=$src n=${stamps.size} " +
            "spread=${"%.1f".format(stamps.spreadUs())}us late=${"%.2f".format(lateMs)}ms xruns=${st[6]}/${st[7]}")
        return Capture(
            pcm = pcm, sr = sr, recFrame0NanoTime = frame0,
            playFramePosition = pos0, playNanoTime = nano0, tsSource = src, recTsSource = "audiotimestamp",
            outputLatencyMs = outputLatencyMs, micSource = micSource, effectsOff = emptyList(),
            playLateMs = lateMs, recTsSpreadUs = spreadUs, framesRecorded = pos,
            captureStartFrame = start, trackDrained = st[0] >= st[1], route = route,
            extraMeta = buildMap {
                put("play_ts_n", stamps.size.toDouble())
                put("play_ts_spread_us", stamps.spreadUs())
                put("rec_ts_n", estimates.size.toDouble())
                put("aaudio_mmap_out", info[2].toDouble())
                put("aaudio_mmap_in", info[3].toDouble())
                put("aaudio_burst_out", info[4].toDouble())
                put("aaudio_burst_in", info[5].toDouble())
                put("aaudio_buffer_out", info[6].toDouble())
                put("aaudio_buffer_in", info[7].toDouble())
                put("aaudio_capacity_out", info[8].toDouble())
                put("aaudio_capacity_in", info[9].toDouble())
                put("aaudio_perf_out", info[10].toDouble())
                put("aaudio_perf_in", info[11].toDouble())
                put("aaudio_input_preset", info[12].toDouble())
                put("aaudio_format_out", info[13].toDouble())
                put("aaudio_format_in", info[14].toDouble())
                if (latOut.isNotEmpty()) put("aaudio_latency_out_ms", AudioTiming.median(latOut))
                if (latIn.isNotEmpty()) put("aaudio_latency_in_ms", AudioTiming.median(latIn))
                put("aaudio_xruns_out", st[6].toDouble())
                put("aaudio_xruns_in", st[7].toDouble())
                put("aaudio_first_frame_out", st[4].toDouble())
                put("aaudio_first_frame_in", st[5].toDouble())
                put("aaudio_max_jump_out", st[12].toDouble())
                put("aaudio_max_jump_in", st[13].toDouble())
            },
            extraMetaStr = mapOf(
                "audio_backend" to BACKEND_AAUDIO,
                "aaudio_sharing_out" to sharing(info[0]),
                "aaudio_sharing_in" to sharing(info[1]),
            ),
        )
    }

    fun close() {
        if (closed) return
        closed = true
        AAudioNative.close(h)
    }
}
