package com.enconomy.pop

import androidx.compose.runtime.Composable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.math.round

/**
 * Audio side of one run (contract §4.2-§4.4). Pure timing math here; the engine itself is
 * androidMain (AndroidAudioEngine). Use from the controller:
 *
 *   engine.preflight()                         -> block on problems (volume, BT/wired route, mic permission)
 *   clock = ClockSync.measure(api)             -> refuse if !clock.ok
 *   arm {attempt, sample_rate = pre.sampleRate, rtt_min_ms = clock.rttMinMs}
 *   engine.prepare(sr, arm.play.decodeF32(sr)) -> opens mic + track, fills 0.3 s primer ‖ play
 *   plan = RunPlan.of(role, sr, t0_ms, clock)
 *   cap = engine.run(plan)                     -> exact CAPTURE_FRAMES int16 + OS timestamps
 *   engine.release()                           (always; also when leaving Running)
 *
 * Then DSP: expectedSelf = cap.expectedSelf(), expectedPartner = cap.expectedPartner(plan),
 * transcript fields: cap.recSha256, cap.playFramePosition, cap.playNanoTime, cap.recFrame0NanoTime.
 *
 * Every derived time is computed from the Long fields that go into the transcript, so the
 * server can redo expected_self from the signed bytes alone.
 */

/** Failure with a contract reason (§8.3), e.g. capture_failed. */
class AudioException(val reason: String, msg: String) : Exception(msg)

data class AudioPreflight(
    val sampleRate: Int,
    val volume: Int,
    val volumeMax: Int,
    /** First external output found (A2DP, headset, USB ...), null = speaker. */
    val externalOutput: String?,
    val micPermission: Boolean,
    val unprocessed: Boolean,
    val outputLatencyMs: Double?,
    /** Blocking, user-facing. */
    val problems: List<String>,
    /** Non-blocking, user-facing. */
    val warnings: List<String>,
) {
    val ok: Boolean get() = problems.isEmpty()
    val volumeFrac: Double get() = if (volumeMax > 0) volume.toDouble() / volumeMax else 0.0
}

interface AudioEngine {
    /** §4.2 rate + §4.3 pre-flight. Cheap; call on the arm screen and right before arm. */
    fun preflight(): AudioPreflight

    /** Media volume to [frac] of max (user tapped "raise volume"). */
    fun setMediaVolume(frac: Double)

    /** Opens AudioRecord + AudioTrack at [sr], fills the track with PRIMER_S zeros ‖ [play]. Throws AudioException. */
    fun prepare(sr: Int, play: FloatArray)

    /** Records, plays at the scheduled time, returns the capture. Throws AudioException(capture_failed). */
    suspend fun run(plan: RunPlan): Capture

    /** Releases mic, track, effects, foreground service. Idempotent. */
    fun release()

    /** Output route, volume and session as the OS reports them now. */
    fun route(): AudioRoute = AudioRoute.UNKNOWN

    /** Session modes the user can pick (iOS; Prefs "audio.mode"). Empty = fixed. */
    val sessionModes: List<String> get() = emptyList()

    /**
     * Audio check only: false skips overrideOutputAudioPort(.speaker) (iOS) so the default route can be
     * compared. Runs always force the speaker; the caller sets it back to true after the check.
     */
    fun setForceSpeaker(on: Boolean) {}
}

expect fun createAudioEngine(): AudioEngine

/** System.nanoTime() on Android. */
expect fun monoNanos(): Long

/** Keeps the screen on while composed with [on] = true (a run must stay foreground). */
@Composable
expect fun KeepScreenOn(on: Boolean = true)

expect fun hasMicPermission(): Boolean

/** Returns a launcher that asks for RECORD_AUDIO; [onResult] gets the grant. */
@Composable
expect fun rememberMicPermissionRequest(onResult: (Boolean) -> Unit): () -> Unit

/** §4.4 schedule, all local nanoTime. */
data class RunPlan(val role: Char, val sr: Int, val t0Ms: Long, val t0Ns: Long) {
    init {
        require(role == 'A' || role == 'B') { "role $role" }
    }

    val playOffsetS: Double get() = if (role == 'A') PopConstants.A_PLAY_S else PopConstants.B_PLAY_S
    val partnerOffsetS: Double get() = if (role == 'A') PopConstants.B_PLAY_S else PopConstants.A_PLAY_S

    val recStartNs: Long get() = t0Ns - REC_PRE_NS
    /** play() call: the primer runs PRIMER_S, so the sound starts at t0 + playOffset. */
    val playCallNs: Long get() = t0Ns + secToNs(playOffsetS - PopConstants.PRIMER_S)
    val stopNs: Long get() = t0Ns + REC_POST_NS
    val captureStartNs: Long get() = t0Ns - secToNs(PopConstants.LEAD_S)
    val primerFrames: Int get() = AudioTiming.primerFrames(sr)
    val captureFrames: Int get() = AudioTiming.captureFrames(sr)

    /** Partner onset, frames in the capture. */
    fun expectedPartner(captureFrame0Ns: Long): Double =
        AudioTiming.frameOf(t0Ns + secToNs(partnerOffsetS), captureFrame0Ns, sr)

    companion object {
        const val REC_PRE_NS = 1_000_000_000L
        const val REC_POST_NS = 2_000_000_000L

        fun of(role: Char, sr: Int, t0Ms: Long, clock: ClockOffset) = RunPlan(role, sr, t0Ms, clock.localNs(t0Ms))
        fun of(role: String, sr: Int, t0Ms: Long, clock: ClockOffset) = of(role.single(), sr, t0Ms, clock)
    }
}

object AudioTiming {
    fun primerFrames(sr: Int): Int = rnd(PopConstants.PRIMER_S * sr)
    fun captureFrames(sr: Int): Int = rnd(PopConstants.CAPTURE_S * sr)
    fun codeFrames(sr: Int): Int = rnd(PopConstants.CODE_S * sr)

    /** Mic frame 0 in nanoTime: ts.nanoTime − ts.framePosition·1e9/sr. */
    fun recFrame0Ns(tsNanoTime: Long, tsFramePosition: Long, sr: Int): Double =
        tsNanoTime - tsFramePosition * 1e9 / sr

    /** Sound onset (track frame PRIMER_FRAMES): ts.nanoTime + (PRIMER_FRAMES − ts.framePosition)·1e9/sr. */
    fun playOnsetNs(tsNanoTime: Long, tsFramePosition: Long, sr: Int): Double =
        tsNanoTime + (primerFrames(sr) - tsFramePosition) * 1e9 / sr

    /** Index (in the recorded stream) of the frame nearest [captureStartNs]. */
    fun captureStartFrame(captureStartNs: Long, recFrame0Ns: Double, sr: Int): Long =
        round((captureStartNs - recFrame0Ns) * sr / 1e9).toLong()

    /** Frame index in the capture of a nanoTime instant. */
    fun frameOf(eventNs: Double, captureFrame0Ns: Long, sr: Int): Double = (eventNs - captureFrame0Ns) * sr / 1e9
    fun frameOf(eventNs: Long, captureFrame0Ns: Long, sr: Int): Double = (eventNs - captureFrame0Ns).toDouble() * sr / 1e9

    fun pcm16Le(x: ShortArray): ByteArray {
        val b = ByteArray(2 * x.size)
        for (i in x.indices) {
            val v = x[i].toInt()
            b[2 * i] = v.toByte(); b[2 * i + 1] = (v shr 8).toByte()
        }
        return b
    }

    /** rec_sha256 (§6.6 step 1, §7.1): sha256 of the capture as int16 LE bytes. */
    fun recSha256(capture: ShortArray): ByteArray = sha256(pcm16Le(capture))

    fun f32Le(b: ByteArray): FloatArray {
        require(b.size % 4 == 0) { "pcm bytes ${b.size} not a multiple of 4" }
        return FloatArray(b.size / 4) { i ->
            val j = 4 * i
            Float.fromBits((b[j].toInt() and 0xff) or ((b[j + 1].toInt() and 0xff) shl 8) or
                ((b[j + 2].toInt() and 0xff) shl 16) or ((b[j + 3].toInt() and 0xff) shl 24))
        }
    }

    /** Median of a non-empty list. */
    fun median(x: List<Double>): Double {
        val s = x.sorted()
        val m = s.size / 2
        return if (s.size % 2 == 1) s[m] else (s[m - 1] + s[m]) / 2
    }

    private fun rnd(x: Double): Int = round(x).toInt()
}

/** §5.3: base64 float32 LE, len == 4·n, n == round(0.25·sr). */
fun Pcm.decodeF32(sr: Int): FloatArray {
    val b = pcm_b64.fromB64()
    if (b.size != 4 * n) throw AudioException("capture_failed", "pcm bytes ${b.size} != 4·$n")
    if (n != AudioTiming.codeFrames(sr)) throw AudioException("capture_failed", "pcm n $n != round(0.25·$sr)")
    return AudioTiming.f32Le(b)
}

/** Templates are float32 on the wire; DSP correlates in double. */
fun Pcm.decodeF64(sr: Int): DoubleArray = decodeF32(sr).let { f -> DoubleArray(f.size) { f[it].toDouble() } }

/**
 * One run's capture. [pcm] is exactly CAPTURE_FRAMES frames starting at t0 − LEAD_S.
 * play* are the raw AudioTimestamp of own playback; with tsSource "fallback" they are
 * framePosition 0, nanoTime = play() call + AudioManager output latency, so the §4.4 onset
 * formula still holds.
 */
class Capture(
    val pcm: ShortArray,
    val sr: Int,
    /** Capture frame 0 in nanoTime (§7.1 rec_frame0_nano_time). */
    val recFrame0NanoTime: Long,
    val playFramePosition: Long,
    val playNanoTime: Long,
    /** "audiotimestamp" | "fallback" */
    val tsSource: String,
    /** "audiotimestamp" | "fallback" (read clock) */
    val recTsSource: String,
    val outputLatencyMs: Double?,
    /** "unprocessed" | "voice_recognition" */
    val micSource: String,
    val effectsOff: List<String>,
    /** Late play() call vs the plan, ms (0 = on time). */
    val playLateMs: Double,
    /** Spread (max − min) of the mic frame-0 estimates, µs. Large = dropped reads. */
    val recTsSpreadUs: Double,
    val framesRecorded: Long,
    val captureStartFrame: Long,
    val trackDrained: Boolean,
    /** Route / session at play time (null = engine does not report it). */
    val route: AudioRoute? = null,
) {
    val recSha256: ByteArray by lazy { AudioTiming.recSha256(pcm) }
    val playOnsetNs: Double get() = AudioTiming.playOnsetNs(playNanoTime, playFramePosition, sr)

    /** Own onset, frames in the capture (§4.4 expected_self). */
    fun expectedSelf(): Double = AudioTiming.frameOf(playOnsetNs, recFrame0NanoTime, sr)
    fun expectedPartner(plan: RunPlan): Double = plan.expectedPartner(recFrame0NanoTime)

    /** Unsigned diagnostics for the transcript meta (§7.1). */
    fun meta(): JsonObject = buildJsonObject {
        put("ts_source", tsSource)
        put("rec_ts_source", recTsSource)
        put("output_latency_ms", outputLatencyMs)
        put("mic_source", micSource)
        put("effects_off", JsonArray(effectsOff.map { JsonPrimitive(it) }))
        put("play_late_ms", playLateMs)
        put("rec_ts_spread_us", recTsSpreadUs)
        put("frames_recorded", framesRecorded)
        put("capture_start_frame", captureStartFrame)
        put("track_drained", trackDrained)
        put("sample_rate", sr)
        route?.putMeta(this)
    }

    /** Own sound vs the lead-in floor, from the capture (diagnostics). */
    fun selfHear(): SelfHear = SelfHear.measure(pcm, sr, expectedSelf())
}

internal fun secToNs(s: Double): Long = round(s * 1e9).toLong()
