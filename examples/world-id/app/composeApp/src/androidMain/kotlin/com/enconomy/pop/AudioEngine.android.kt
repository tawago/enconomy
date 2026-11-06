package com.enconomy.pop

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTimestamp
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AudioEffect
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import android.os.Build
import android.os.Process
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalView
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

private const val TAG = "PopAudio"

actual fun createAudioEngine(): AudioEngine = AndroidAudioEngine(PopApplication.instance)

actual fun monoNanos(): Long = System.nanoTime()

@Composable
actual fun KeepScreenOn(on: Boolean) {
    val view = LocalView.current
    DisposableEffect(view, on) {
        view.keepScreenOn = on
        onDispose { view.keepScreenOn = false }
    }
}

actual fun hasMicPermission(): Boolean =
    ContextCompat.checkSelfPermission(PopApplication.instance, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

@Composable
actual fun rememberMicPermissionRequest(onResult: (Boolean) -> Unit): () -> Unit {
    val cb = rememberUpdatedState(onResult)
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { cb.value(it) }
    return { if (hasMicPermission()) cb.value(true) else launcher.launch(Manifest.permission.RECORD_AUDIO) }
}

/**
 * Contract §4.2-§4.4 on Android.
 *
 * Mic: UNPROCESSED when the HAL says so, else VOICE_RECOGNITION; int16 mono; buffer ≥ 1 s;
 * AEC/NS/AGC created on the session and disabled when available. The whole recording
 * (rec start .. stop) stays in memory; the capture is cut out afterwards.
 *
 * Speaker: float mono MODE_STATIC low-latency track, PRIMER_S zeros ‖ play PCM, so the
 * output path is already running 0.3 s before the sound (decision note §2, glitch).
 *
 * Times: mic frame 0 = median over AudioRecord.getTimestamp(MONOTONIC) readings after 0.5 s
 * of recording (fallback: min over reads of now − framesRead/sr). Playback timestamp = the
 * AudioTrack.getTimestamp reading with the median onset among the advancing ones read while the track
 * plays (fallback: the reading after drain, then play() call + latency). The after-drain reading alone
 * was used before: the static track has stopped by then, and the Pixel 6 returned the same frozen
 * framePosition 23040 (= 26400 − 3360) every run; it stays in the meta for comparison.

 *
 * Backend (Prefs "audio.backend"): "aaudio" = AAudioSession (NDK, LOW_LATENCY + EXCLUSIVE/MMAP, AAudio
 * timestamps; the Pixel 6's Java timestamps put its own sound ~10.8 ms late), "java" = the path above.
 * Unset: aaudio when both streams open MMAP exclusive, else java.
 */
class AndroidAudioEngine(private val ctx: Context) : AudioEngine {
    private val am: AudioManager = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    /** Open AAudio duplex (backend "aaudio"), else the AudioRecord/AudioTrack pair above is used. */
    private var aa: AAudioSession? = null
    /** Why the last prepare fell back from AAudio to Java ("" = it did not). */
    private var fallbackNote = ""

    override val sessionModes: List<String> get() = if (AAudioNative.available) listOf(BACKEND_AAUDIO, BACKEND_JAVA) else emptyList()
    override val modePrefKey: String get() = BACKEND_PREF
    override val defaultMode: String get() = if (AAudioNative.available && mmapExclusiveOk()) BACKEND_AAUDIO else BACKEND_JAVA
    override val modeTitle: String get() = "Audio backend"

    override fun modeNote(): String {
        aa?.let { return it.describe() }
        lastAAudioDesc?.let { if (wantedBackend() == BACKEND_AAUDIO && fallbackNote.isEmpty()) return "Last run: $it" }
        return when {
            fallbackNote.isNotEmpty() -> "Java (AAudio fell back: $fallbackNote)"
            wantedBackend() == BACKEND_AAUDIO -> "AAudio, MMAP exclusive requested"
            else -> "Java AudioTrack / AudioRecord"
        }
    }

    /** Prefs "audio.backend"; unset = aaudio when this device grants MMAP exclusive, else java. */
    private fun wantedBackend(): String = when (Prefs.get(BACKEND_PREF)) {
        BACKEND_AAUDIO -> if (AAudioNative.available) BACKEND_AAUDIO else BACKEND_JAVA
        BACKEND_JAVA -> BACKEND_JAVA
        else -> defaultMode
    }

    override val inputPresets: List<Pair<String, String>>
        get() = PRESETS.filter { it.key != PRESET_VOICE_PERFORMANCE || Build.VERSION.SDK_INT >= 29 }.map { it.key.toString() to it.value.second }

    override val defaultInputPreset: String get() = defaultPreset().toString()

    private fun defaultPreset(): Int =
        if (unprocessedSupported()) AAudioNative.PRESET_UNPROCESSED else AAudioNative.PRESET_VOICE_RECOGNITION

    /**
     * Prefs "audio.input" (AAudio input preset = MediaRecorder.AudioSource number, same values); unset = UNPROCESSED
     * when the HAL says so, else VOICE_RECOGNITION. A picked preset is requested even if reported unsupported.
     */
    private fun inputPreset(): Int =
        Prefs.get(INPUT_PRESET_PREF)?.toIntOrNull()?.takeIf { it in PRESETS && (it != PRESET_VOICE_PERFORMANCE || Build.VERSION.SDK_INT >= 29) }
            ?: defaultPreset()

    /** Opens both AAudio streams exclusive once (no start) and checks both were granted exclusive. Cached. */
    private fun mmapExclusiveOk(): Boolean {
        probeResult?.let { return it }
        if (!hasMicPermission() || aa != null) return false
        val h = AAudioNative.open(sampleRate(), true, inputPreset(), null, 0)
        if (h == 0L) {
            Log.w(TAG, "aaudio probe: ${AAudioNative.lastError()}")
            probeResult = false
            return false
        }
        val info = try { AAudioNative.info(h) } finally { AAudioNative.close(h) }
        val ok = info[0] == AAudioNative.SHARING_EXCLUSIVE && info[1] == AAudioNative.SHARING_EXCLUSIVE
        Log.i(TAG, "aaudio probe: exclusive out=${info[0] == 0} in=${info[1] == 0} mmap out=${info[2]} in=${info[3]}")
        probeResult = ok
        return ok
    }

    private var rec: AudioRecord? = null
    private var track: AudioTrack? = null
    private var effects: List<AudioEffect> = emptyList()
    private var effectsOff: List<String> = emptyList()
    private var micSource = ""
    private var javaSource = 0
    private var sr = 0
    private var trackFrames = 0

    fun sampleRate(): Int {
        val r = am.getProperty(AudioManager.PROPERTY_OUTPUT_SAMPLE_RATE)?.toIntOrNull()
        return if (r != null && r in PopConstants.SR_MIN..PopConstants.SR_MAX) r else 48000
    }

    private fun unprocessedSupported(): Boolean =
        am.getProperty(AudioManager.PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED) == "true"

    /** AudioManager.getOutputLatency is hidden; else 2 × frames per buffer. */
    fun outputLatencyMs(): Double? {
        try {
            val m = AudioManager::class.java.getMethod("getOutputLatency", Int::class.javaPrimitiveType)
            val v = m.invoke(am, AudioManager.STREAM_MUSIC) as Int
            if (v > 0) return v.toDouble()
        } catch (_: Throwable) {
        }
        val fpb = am.getProperty(AudioManager.PROPERTY_OUTPUT_FRAMES_PER_BUFFER)?.toIntOrNull() ?: return null
        return 2.0 * fpb * 1000.0 / sampleRate()
    }

    override fun preflight(): AudioPreflight {
        val vol = am.getStreamVolume(AudioManager.STREAM_MUSIC)
        val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val ext = externalOutput()
        val mic = hasMicPermission()
        val unp = unprocessedSupported()
        val problems = mutableListOf<String>()
        val warnings = mutableListOf<String>()
        if (!mic) problems += "Microphone permission needed."
        if (max <= 0 || vol < 0.6 * max) problems += "Media volume too low (${vol}/${max}). Raise it to at least 60%."
        if (ext != null) problems += "Audio goes to $ext. Disconnect it so the phone speaker plays."
        if (!hasBuiltinSpeaker()) warnings += "No built-in speaker reported."
        if (!unp && Prefs.get(INPUT_PRESET_PREF) == null) warnings += "Unprocessed mic not supported; using voice recognition source."
        if (am.isMusicActive) warnings += "Other audio is playing; stop it for a clean run."
        return AudioPreflight(sampleRate(), vol, max, ext, mic, unp, outputLatencyMs(), problems, warnings)
    }

    override fun setMediaVolume(frac: Double) {
        val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val v = (frac.coerceIn(0.0, 1.0) * max).roundToInt()
        try {
            am.setStreamVolume(AudioManager.STREAM_MUSIC, v, AudioManager.FLAG_SHOW_UI)
        } catch (e: SecurityException) {
            Log.w(TAG, "setStreamVolume: $e") // DND policy
        }
    }

    private fun externalOutput(): String? {
        val bad = mutableSetOf(
            AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
            AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
            AudioDeviceInfo.TYPE_USB_HEADSET, AudioDeviceInfo.TYPE_USB_DEVICE, AudioDeviceInfo.TYPE_LINE_ANALOG,
        )
        if (Build.VERSION.SDK_INT >= 28) bad += AudioDeviceInfo.TYPE_HEARING_AID
        if (Build.VERSION.SDK_INT >= 31) {
            bad += AudioDeviceInfo.TYPE_BLE_HEADSET; bad += AudioDeviceInfo.TYPE_BLE_SPEAKER
        }
        val d = am.getDevices(AudioManager.GET_DEVICES_OUTPUTS).firstOrNull { it.type in bad } ?: return null
        val name = d.productName?.toString()?.takeIf { it.isNotBlank() }
        return name ?: when (d.type) {
            AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "Bluetooth"
            AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> "headphones"
            else -> "an external device"
        }
    }

    override fun route(): AudioRoute = routeOf(track?.routedDevice ?: guessOutput())

    /** Media output the policy would pick: first external device, else the built-in speaker. */
    private fun guessOutput(): AudioDeviceInfo? {
        val outs = am.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
        return outs.firstOrNull { kindOf(it.type) !in setOf("speaker", "earpiece", "other") }
            ?: outs.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
    }

    private fun kindOf(type: Int): String = when (type) {
        AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> "speaker"
        AudioDeviceInfo.TYPE_BUILTIN_EARPIECE -> "earpiece"
        AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "bluetooth"
        AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> "headphones"
        AudioDeviceInfo.TYPE_USB_HEADSET, AudioDeviceInfo.TYPE_USB_DEVICE -> "usb"
        else -> if (Build.VERSION.SDK_INT >= 31 && (type == AudioDeviceInfo.TYPE_BLE_HEADSET || type == AudioDeviceInfo.TYPE_BLE_SPEAKER)) "bluetooth"
        else "other"
    }

    private fun routeOf(d: AudioDeviceInfo?): AudioRoute {
        val vol = am.getStreamVolume(AudioManager.STREAM_MUSIC)
        val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val kind = d?.let { kindOf(it.type).let { k -> if (k == "other") "other:${it.type}" else k } } ?: "unknown"
        val mode = micSource.ifEmpty { presetName(inputPreset()) }
        val detail = listOfNotNull(
            aa?.describe() ?: BACKEND_JAVA,
            "stream ${vol}/${max}",
            if (track != null) "routed" else "guessed",
            effectsOff.takeIf { it.isNotEmpty() }?.let { "fx off ${it.joinToString(",")}" },
        ).joinToString(", ")
        return AudioRoute(kind, d?.productName?.toString() ?: "", if (max > 0) vol.toDouble() / max else 0.0, mode,
            if (sr > 0) sr else sampleRate(), detail)
    }

    private fun hasBuiltinSpeaker() =
        am.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }

    @SuppressLint("MissingPermission")
    override fun prepare(sr: Int, play: FloatArray) {
        release()
        if (!hasMicPermission()) throw AudioException("capture_failed", "no RECORD_AUDIO permission")
        require(sr in PopConstants.SR_MIN..PopConstants.SR_MAX) { "sr $sr" }
        this.sr = sr
        PopAudioService.start(ctx)
        fallbackNote = ""
        if (wantedBackend() == BACKEND_AAUDIO) {
            val explicit = Prefs.get(BACKEND_PREF) == BACKEND_AAUDIO
            val primer = AudioTiming.primerFrames(sr)
            val buf = FloatArray(primer + play.size)
            play.copyInto(buf, primer)
            val recFrames = ((RunPlan.REC_PRE_NS + RunPlan.REC_POST_NS) / 1e9 * sr + 2.0 * sr).toInt()
            val preset = inputPreset()
            micSource = presetName(preset)
            val h = AAudioNative.open(sr, true, preset, buf, recFrames)
            if (h == 0L) {
                fallbackNote = AAudioNative.lastError()
                Log.w(TAG, "aaudio open failed, java: $fallbackNote")
            } else {
                val s = AAudioSession(h, sr, micSource, preset)
                // explicit "aaudio" keeps whatever sharing was granted; the auto default needs exclusive both ways
                if (explicit || s.exclusive) {
                    aa = s
                    lastAAudioDesc = s.describe()
                    Log.i(TAG, "aaudio: ${s.describe()}")
                    return
                }
                fallbackNote = "not exclusive (${s.describe()})"
                s.close()
            }
        }
        try {
            openRecord(sr)
            openTrack(sr, play)
        } catch (e: Throwable) {
            release()
            if (e is AudioException) throw e
            throw AudioException("capture_failed", "audio open: ${e.message}")
        }
    }

    @SuppressLint("MissingPermission")
    private fun openRecord(sr: Int) {
        val source = inputPreset() // MediaRecorder.AudioSource: same numbers as the AAudio presets
        javaSource = source
        micSource = presetName(source)
        val min = AudioRecord.getMinBufferSize(sr, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (min <= 0) throw AudioException("capture_failed", "AudioRecord.getMinBufferSize($sr) = $min")
        val r = AudioRecord.Builder()
            .setAudioSource(source)
            .setAudioFormat(
                AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(sr).setChannelMask(AudioFormat.CHANNEL_IN_MONO).build(),
            )
            .setBufferSizeInBytes(maxOf(min, 2 * sr)) // ≥ 1 s int16
            .let { b -> try { b.build() } catch (e: Exception) { throw AudioException("capture_failed", "AudioRecord source $source: ${e.message}") } }
        rec = r
        if (r.state != AudioRecord.STATE_INITIALIZED) throw AudioException("capture_failed", "AudioRecord not initialized")
        if (r.sampleRate != sr) throw AudioException("capture_failed", "mic runs at ${r.sampleRate}, wanted $sr")
        val fx = mutableListOf<AudioEffect>()
        val off = mutableListOf<String>()
        fun disable(name: String, available: Boolean, make: () -> AudioEffect?) {
            if (!available) return
            try {
                val e = make() ?: return
                e.enabled = false
                fx += e
                if (!e.enabled) off += name
            } catch (t: Throwable) {
                Log.w(TAG, "$name: $t")
            }
        }
        val sid = r.audioSessionId
        disable("aec", AcousticEchoCanceler.isAvailable()) { AcousticEchoCanceler.create(sid) }
        disable("ns", NoiseSuppressor.isAvailable()) { NoiseSuppressor.create(sid) }
        disable("agc", AutomaticGainControl.isAvailable()) { AutomaticGainControl.create(sid) }
        effects = fx
        effectsOff = off
    }

    private fun openTrack(sr: Int, play: FloatArray) {
        val primer = AudioTiming.primerFrames(sr)
        val buf = FloatArray(primer + play.size)
        play.copyInto(buf, primer)
        val b = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build(),
            )
            .setAudioFormat(
                AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_FLOAT)
                    .setSampleRate(sr).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build(),
            )
            .setTransferMode(AudioTrack.MODE_STATIC)
            .setBufferSizeInBytes(4 * buf.size)
        if (Build.VERSION.SDK_INT >= 26) b.setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
        val t = b.build()
        track = t
        val n = t.write(buf, 0, buf.size, AudioTrack.WRITE_BLOCKING)
        if (n != buf.size) throw AudioException("capture_failed", "AudioTrack.write = $n of ${buf.size}")
        if (t.state != AudioTrack.STATE_INITIALIZED) throw AudioException("capture_failed", "AudioTrack not initialized (${t.state})")
        if (t.sampleRate != sr) throw AudioException("capture_failed", "track runs at ${t.sampleRate}, wanted $sr")
        trackFrames = buf.size
    }

    override suspend fun run(plan: RunPlan): Capture = withContext(Dispatchers.IO) {
        check(plan.sr == sr) { "plan sr ${plan.sr} != prepared $sr" }
        val a = aa
        val oldPrio = Process.getThreadPriority(Process.myTid())
        Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_AUDIO)
        try {
            if (a != null) {
                a.record(plan, outputLatencyMs(), runCatching { routeOf(guessOutput()) }.getOrNull())
            } else {
                val r = rec ?: throw AudioException("capture_failed", "not prepared")
                val t = track ?: throw AudioException("capture_failed", "not prepared")
                record(r, t, plan)
            }
        } finally {
            Process.setThreadPriority(oldPrio)
        }
    }

    private fun record(r: AudioRecord, t: AudioTrack, plan: RunPlan): Capture {
        val player = Player(t, plan, trackFrames)
        val pt = Thread(player, "pop-play").apply { priority = Thread.MAX_PRIORITY }

        // whole recording in memory: rec start .. stop + margin
        val buf = ShortArray(((plan.stopNs - plan.recStartNs) / 1e9 * sr + 2.0 * sr).toInt())
        val chunk = sr / 100
        val halfSec = sr / 2
        val estimates = ArrayList<Double>()
        var fallback0 = Double.MAX_VALUE
        var pos = 0
        var lastTsAt = 0
        val rts = AudioTimestamp()

        sleepUntil(plan.recStartNs)
        r.startRecording()
        if (r.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
            throw AudioException("capture_failed", "mic did not start (in use by another app?)")
        }
        pt.start()
        val hardStop = plan.stopNs + 1_500_000_000L
        try {
            while (pos < buf.size) {
                val n = r.read(buf, pos, minOf(chunk, buf.size - pos), AudioRecord.READ_BLOCKING)
                if (n < 0) throw AudioException("capture_failed", "AudioRecord.read = $n")
                val now = System.nanoTime()
                pos += n
                fallback0 = minOf(fallback0, now - pos * 1e9 / sr)
                if (pos >= halfSec && pos - lastTsAt >= chunk * 5) {
                    lastTsAt = pos
                    if (r.getTimestamp(rts, AudioTimestamp.TIMEBASE_MONOTONIC) == AudioRecord.SUCCESS && rts.framePosition > 0) {
                        estimates += AudioTiming.recFrame0Ns(rts.nanoTime, rts.framePosition, sr)
                    }
                }
                if (now >= plan.stopNs + 100_000_000L && player.done) {
                    val f0 = if (estimates.isNotEmpty()) AudioTiming.median(estimates) else fallback0
                    val need = AudioTiming.captureStartFrame(plan.captureStartNs, f0, sr) + plan.captureFrames
                    if (pos >= need || now >= hardStop) break
                }
                if (now >= hardStop + 1_000_000_000L) break
            }
        } finally {
            runCatching { r.stop() }
            player.cancel = true
            pt.join(3000)
        }

        val recTsSource = if (estimates.isNotEmpty()) "audiotimestamp" else "fallback"
        val f0 = if (estimates.isNotEmpty()) AudioTiming.median(estimates) else fallback0
        val spreadUs = if (estimates.size > 1) (estimates.max() - estimates.min()) / 1e3 else 0.0
        val start = AudioTiming.captureStartFrame(plan.captureStartNs, f0, sr)
        val frames = plan.captureFrames
        if (start < 0 || start + frames > pos) {
            throw AudioException("capture_failed", "capture [$start, ${start + frames}) outside recorded [0, $pos)")
        }
        val pcm = buf.copyOfRange(start.toInt(), start.toInt() + frames)
        val frame0 = kotlin.math.round(f0 + start * 1e9 / sr).toLong()

        val latency = outputLatencyMs()
        val route = runCatching { routeOf(t.routedDevice) }.getOrNull()
        val drainTs = player.drainTs
        val ts = player.pick() ?: drainTs
        val (pos0, nano0, src) = if (ts != null) Triple(ts.first, ts.second, "audiotimestamp")
        else Triple(0L, player.calledNs + kotlin.math.round((latency ?: 0.0) * 1e6).toLong(), "fallback")
        if (player.calledNs == 0L) throw AudioException("capture_failed", "play() never called")
        Log.i(TAG, "rec src=$micSource fx_off=$effectsOff f0=$recTsSource spread=${"%.1f".format(spreadUs)}us " +
            "play ts=$src pos=$pos0 late=${"%.2f".format(player.lateMs)}ms drained=${player.drained}")
        return Capture(
            pcm = pcm, sr = sr, recFrame0NanoTime = frame0,
            playFramePosition = pos0, playNanoTime = nano0, tsSource = src, recTsSource = recTsSource,
            outputLatencyMs = latency, micSource = micSource, effectsOff = effectsOff,
            playLateMs = player.lateMs, recTsSpreadUs = spreadUs, framesRecorded = pos.toLong(),
            captureStartFrame = start, trackDrained = player.drained, route = route,
            extraMeta = buildMap {
                put("play_ts_n", player.stampCount().toDouble())
                put("play_ts_spread_us", player.stampSpreadUs())
                put("input_preset_requested", javaSource.toDouble())
                put("input_preset_granted", r.audioSource.toDouble())
                if (ts != null && drainTs != null) {
                    // after-drain onset − used onset (0 when the fallback is the drain reading itself)
                    put("play_drain_onset_diff_us", (AudioTiming.playOnsetNs(drainTs.second, drainTs.first, sr) -
                        AudioTiming.playOnsetNs(ts.second, ts.first, sr)) / 1e3)
                }
            },
            extraMetaStr = buildMap {
                put("audio_backend", BACKEND_JAVA)
                if (fallbackNote.isNotEmpty()) put("audio_backend_fallback", fallbackNote)
            },
        )
    }

    /** Calls play() at plan.playCallNs, keeps the advancing AudioTimestamps while playing and the one after drain. */
    private class Player(val t: AudioTrack, val plan: RunPlan, val frames: Int) : Runnable {
        @Volatile var done = false
        @Volatile var cancel = false
        @Volatile var calledNs = 0L
        @Volatile var lateMs = 0.0
        @Volatile var drained = false
        @Volatile var drainTs: Pair<Long, Long>? = null
        private val stamps = PlayStamps(plan.sr)

        fun pick(): Pair<Long, Long>? = synchronized(stamps) { stamps.pick() }
        fun stampCount(): Int = synchronized(stamps) { stamps.size }
        fun stampSpreadUs(): Double = synchronized(stamps) { stamps.spreadUs() }

        override fun run() {
            try {
                Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_AUDIO)
                sleepUntil(plan.playCallNs)
                calledNs = System.nanoTime()
                t.play()
                lateMs = maxOf(0.0, (calledNs - plan.playCallNs) / 1e6)
                val a = AudioTimestamp()
                val end = calledNs + (frames * 1e9 / plan.sr).toLong() + 1_000_000_000L
                while (!cancel && System.nanoTime() < end) {
                    if (t.playbackHeadPosition >= frames) {
                        drained = true
                        break
                    }
                    if (t.playState == AudioTrack.PLAYSTATE_PLAYING && t.getTimestamp(a)) {
                        synchronized(stamps) { stamps.add(a.framePosition, a.nanoTime) }
                    }
                    Thread.sleep(10)
                }
                if (t.getTimestamp(a) && a.framePosition > 0) drainTs = a.framePosition to a.nanoTime // after drain, meta
            } catch (e: Throwable) {
                Log.w(TAG, "player: $e")
            } finally {
                done = true
            }
        }
    }

    override fun release() {
        aa?.close()
        aa = null
        effects.forEach { runCatching { it.release() } }
        effects = emptyList()
        rec?.let { r -> runCatching { if (r.recordingState == AudioRecord.RECORDSTATE_RECORDING) r.stop() }; r.release() }
        rec = null
        track?.let { t -> runCatching { t.pause(); t.flush() }; t.release() }
        track = null
        PopAudioService.stop(ctx)
    }
}

const val BACKEND_PREF = "audio.backend"

private const val PRESET_VOICE_PERFORMANCE = 10

/** AAudio input preset = MediaRecorder.AudioSource number -> (meta name, picker label). */
private val PRESETS = linkedMapOf(
    6 to ("voice_recognition" to "VoiceRec"),
    9 to ("unprocessed" to "Unproc"),
    5 to ("camcorder" to "Camcorder"),
    1 to ("generic" to "Generic"),
    10 to ("voice_performance" to "VoicePerf"),
)

internal fun presetName(p: Int): String = PRESETS[p]?.first ?: "preset_$p"
const val BACKEND_AAUDIO = "aaudio"
const val BACKEND_JAVA = "java"

/** MMAP-exclusive probe result for this process (null = not probed yet). */
private var probeResult: Boolean? = null
private var lastAAudioDesc: String? = null

/** Coarse sleep to ~2 ms before [targetNs], then spin. */
internal fun sleepUntil(targetNs: Long) {
    while (true) {
        val d = targetNs - System.nanoTime()
        if (d <= 0) return
        if (d > 3_000_000L) Thread.sleep((d - 2_000_000L) / 1_000_000L)
    }
}
