package com.enconomy.pop

import kotlinx.coroutines.await
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.max
import kotlin.math.round

actual fun createAudioEngine(): AudioEngine = WebAudioEngine()

internal fun audioOffsetMs(): Double = js("window.popAudio.offsetMs()")

/**
 * Contract §4.2-§4.4 in the browser, on the pop-audio.js glue.
 *
 * Clock: monoNanos() = performance.now()·1e6. Context time maps onto it through the median
 * (performanceTime − contextTime·1000) of recent getOutputTimestamp() readings, i.e. "when that context frame
 * is heard". So:
 *  - playback: track frame 0 (primer start) is scheduled at the context time whose heard instant is the plan's
 *    play() instant; playNanoTime = heard instant of the start actually used, playFramePosition = 0
 *    (tsSource "fallback" shape: onset = playNanoTime + PRIMER_FRAMES/sr).
 *  - mic: the block the worklet sees at context frame F holds sound captured about (outputLatency + input
 *    latency) before F is heard, so frame F's capture instant = ctxToPerf(F/sr) − that lag. The input latency
 *    is MediaStreamTrack settings.latency when the browser reports it, else ctx.baseLatency.
 * What is left over is constant per device and ends up in the enrollment calibration (cal_us).
 */
class WebAudioEngine : AudioEngine {
    private var sr = 0
    private var track: JsAny? = null
    private var trackFrames = 0

    private fun info(): JsonObject = runCatching { Json.parseToJsonElement(audioInfoJson()).jsonObject }.getOrElse { JsonObject(emptyMap()) }
    private fun JsonObject.d(k: String): Double? = this[k]?.let { runCatching { it.jsonPrimitive.doubleOrNull }.getOrNull() }
    private fun JsonObject.b(k: String): Boolean? = this[k]?.let { runCatching { it.jsonPrimitive.booleanOrNull }.getOrNull() }

    override val modeTitle: String get() = "Web Audio"
    override fun modeNote(): String {
        val i = info()
        return "AudioContext ${i.d("sampleRate")?.toInt() ?: "?"} Hz, out ${f1((i.d("outputLatency") ?: 0.0) * 1000)} ms, " +
            "in ${i.d("inputLatency")?.let { f1(it * 1000) } ?: "?"} ms, drops ${i.d("drops")?.toInt() ?: 0}"
    }

    override fun route(): AudioRoute {
        val i = info()
        // browsers do not report the route: assumed speaker (preflight tells the user)
        return AudioRoute("speaker", "browser (assumed)", 1.0, "webaudio", i.d("sampleRate")?.toInt() ?: 48000, "web audio, route not reported")
    }

    override fun preflight(): AudioPreflight {
        val i = info()
        val unlocked = audioUnlocked()
        val rate = i.d("sampleRate")?.toInt()?.takeIf { it > 0 } ?: 48000
        val s = i["settings"]?.let { runCatching { it.jsonObject }.getOrNull() } ?: JsonObject(emptyMap())
        val on = listOf("echoCancellation" to "echo cancellation", "noiseSuppression" to "noise suppression", "autoGainControl" to "auto gain")
            .filter { (k, _) -> s.b(k) == true }.map { it.second }
        val problems = mutableListOf<String>()
        val warnings = mutableListOf<String>()
        if (!unlocked) problems += "Tap to allow the microphone (audio is not started in this tab)."
        if (unlocked && rate != 48000) problems += "Audio runs at $rate Hz; this web build needs 48000 Hz."
        if (on.isNotEmpty()) problems += "The browser keeps ${on.joinToString(", ")} on; use Chrome on Android or desktop."
        warnings += "Browsers do not report volume or output route: turn media volume up and use the built-in speaker (no Bluetooth)."
        if (i.b("outputTs") != true && unlocked) warnings += "No output timestamp from this browser yet; timing is a rough estimate."
        val outMs = i.d("outputLatency")?.let { it * 1000 }
        return AudioPreflight(rate, 1, 1, null, audioMicGranted(), on.isEmpty(), outMs, problems, warnings)
    }

    override fun setMediaVolume(frac: Double) {}

    override fun prepare(sr: Int, play: FloatArray) {
        release()
        if (!audioUnlocked()) throw AudioException("capture_failed", "audio not started in this tab (tap to allow the mic)")
        val ctxRate = info().d("sampleRate")?.toInt() ?: 0
        if (ctxRate != sr) throw AudioException("capture_failed", "AudioContext runs at $ctxRate, wanted $sr")
        this.sr = sr
        val primer = AudioTiming.primerFrames(sr)
        val n = primer + play.size
        val buf = audioNewBuffer(n)
        for (k in play.indices) audioBufSet(buf, primer + k, play[k])
        track = buf
        trackFrames = n
    }

    override suspend fun run(plan: RunPlan): Capture {
        check(plan.sr == sr) { "plan sr ${plan.sr} != prepared $sr" }
        val buf = track ?: throw AudioException("capture_failed", "not prepared")
        val i0 = info()
        val outLatS = i0.d("outputLatency") ?: 0.0
        val inLatReported = i0.d("inputLatency")
        val inLatS = inLatReported ?: (i0.d("baseLatency") ?: 0.0)
        val lagS = outLatS + inLatS
        val drops0 = i0.d("drops")?.toInt() ?: 0

        // playback: heard(track frame 0) = plan.playCallNs
        val off0 = audioOffsetMs()
        val wantS = (plan.playCallNs / 1e6 - off0) / 1000.0
        val usedS = audioSchedule(buf, wantS)
        val lateMs = max(0.0, (usedS - wantS) * 1000)

        // capture window: CAPTURE_FRAMES from the context frame whose capture instant is plan.captureStartNs
        val startFrame = round(((plan.captureStartNs / 1e6 - off0) / 1000.0 + lagS) * sr).toLong()
        val waitMs = ((plan.stopNs - monoNanos()) / 1_000_000L + 4000L).coerceIn(4000L, 30_000L).toInt()
        val samples = try {
            audioCollect(startFrame.toDouble(), plan.captureFrames, waitMs).await<JsAny?>()
                ?: throw AudioException("capture_failed", "no capture")
        } catch (e: AudioException) {
            throw e
        } catch (e: Throwable) {
            throw AudioException("capture_failed", "mic: ${e.message}")
        }

        val n = audioBufLen(samples)
        if (n != plan.captureFrames) throw AudioException("capture_failed", "capture $n frames, wanted ${plan.captureFrames}")
        val pcm = ShortArray(n) { k ->
            val v = audioBufGet(samples, k)
            round(v.coerceIn(-1f, 1f) * 32767f).toInt().toShort()
        }

        // one clock mapping for both ends, read after the run
        val off = audioOffsetMs()
        val playNano = round((usedS * 1000.0 + off) * 1e6).toLong()
        val frame0 = round(((startFrame.toDouble() / sr) * 1000.0 + off - lagS * 1000.0) * 1e6).toLong()
        val i1 = info()
        val drops = (i1.d("drops")?.toInt() ?: 0) - drops0
        return Capture(
            pcm = pcm, sr = sr, recFrame0NanoTime = frame0,
            playFramePosition = 0, playNanoTime = playNano, tsSource = "fallback",
            recTsSource = if (i1.b("outputTs") == true) "output_timestamp" else "fallback",
            outputLatencyMs = outLatS * 1000, micSource = "webaudio",
            effectsOff = listOf("aec", "ns", "agc").takeIf { preflight().unprocessed } ?: emptyList(),
            playLateMs = lateMs, recTsSpreadUs = kotlin.math.abs(off - off0) * 1000, framesRecorded = n.toLong(),
            captureStartFrame = startFrame, trackDrained = true, route = route(),
            extraMeta = buildMap {
                put("web_output_latency_ms", outLatS * 1000)
                put("web_input_latency_ms", inLatS * 1000)
                put("web_base_latency_ms", (i0.d("baseLatency") ?: 0.0) * 1000)
                put("web_clock_offset_drift_us", (off - off0) * 1000)
                put("web_drops", drops.toDouble())
            },
            extraMetaStr = buildMap {
                put("audio_backend", "webaudio")
                put("web_input_latency_src", if (inLatReported != null) "track_settings" else "base_latency")
                put("web_ua", jsUserAgent().take(160))
            },
        )
    }

    override fun release() {
        audioStopAll()
        track = null
    }

    private fun f1(x: Double): String = (round(x * 10) / 10).toString()
}
