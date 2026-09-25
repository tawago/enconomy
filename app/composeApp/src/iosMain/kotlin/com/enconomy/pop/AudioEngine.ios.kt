@file:OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)

package com.enconomy.pop

import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.ObjCObjectVar
import kotlinx.cinterop.alloc
import kotlinx.cinterop.get
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.set
import kotlinx.cinterop.value
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import platform.AVFAudio.AVAudioEngine
import platform.AVFAudio.AVAudioEngineConfigurationChangeNotification
import platform.AVFAudio.AVAudioFormat
import platform.AVFAudio.AVAudioPCMBuffer
import platform.AVFAudio.AVAudioPlayerNode
import platform.AVFAudio.AVAudioPlayerNodeCompletionDataPlayedBack
import platform.AVFAudio.AVAudioSession
import platform.AVFAudio.AVAudioSessionCategoryOptionDefaultToSpeaker
import platform.AVFAudio.AVAudioSessionCategoryPlayAndRecord
import platform.AVFAudio.AVAudioSessionInterruptionNotification
import platform.AVFAudio.AVAudioSessionInterruptionTypeBegan
import platform.AVFAudio.AVAudioSessionInterruptionTypeKey
import platform.AVFAudio.AVAudioSessionMediaServicesWereResetNotification
import platform.AVFAudio.AVAudioSessionModeMeasurement
import platform.AVFAudio.AVAudioSessionPortBuiltInMic
import platform.AVFAudio.AVAudioSessionPortBuiltInReceiver
import platform.AVFAudio.AVAudioSessionPortBuiltInSpeaker
import platform.AVFAudio.AVAudioSessionPortDescription
import platform.AVFAudio.AVAudioSessionRouteChangeReasonNewDeviceAvailable
import platform.AVFAudio.AVAudioSessionRouteChangeNotification
import platform.AVFAudio.AVAudioSessionRouteChangeReasonOldDeviceUnavailable
import platform.AVFAudio.AVAudioSessionRouteChangeReasonKey
import platform.AVFAudio.AVAudioSessionSetActiveOptionNotifyOthersOnDeactivation
import platform.AVFAudio.AVAudioTime
import platform.AVFAudio.currentRoute
import platform.AVFAudio.inputLatency
import platform.AVFAudio.otherAudioPlaying
import platform.AVFAudio.outputLatency
import platform.AVFAudio.outputVolume
import platform.AVFAudio.sampleRate
import platform.AVFAudio.setActive
import platform.AVFAudio.setPreferredSampleRate
import platform.AVFAudio.IOBufferDuration
import platform.Foundation.NSError
import platform.Foundation.NSLock
import platform.Foundation.NSNotification
import platform.Foundation.NSNotificationCenter
import platform.Foundation.NSNumber
import platform.darwin.NSObjectProtocol
import kotlin.concurrent.Volatile
import kotlin.math.round

actual fun createAudioEngine(): AudioEngine = IosAudioEngine()

/** Host tick -> ns ratio (125/3 on arm64, 1/1 on Intel), from AVAudioTime ticks per second. */
internal object HostClock {
    val numer: Long
    val denom: Long

    init {
        val tps = AVAudioTime.hostTimeForSeconds(1.0).toLong().coerceAtLeast(1)
        val g = gcd(1_000_000_000L, tps)
        numer = 1_000_000_000L / g
        denom = tps / g
    }

    private fun gcd(a: Long, b: Long): Long = if (b == 0L) a else gcd(b, a % b)

    fun toNs(host: ULong): Long = hostTicksToNs(host.toLong(), numer, denom)
    fun toHost(ns: Long): ULong = nsToHostTicks(ns, numer, denom).toULong()
}

/** Split multiply so ticks·numer never overflows. */
internal fun hostTicksToNs(ticks: Long, numer: Long, denom: Long): Long =
    ticks / denom * numer + ticks % denom * numer / denom

/** Inverse of [hostTicksToNs], rounded to the nearest tick. */
internal fun nsToHostTicks(ns: Long, numer: Long, denom: Long): Long =
    ns / numer * denom + (ns % numer * denom + numer / 2) / numer

/** float -> int16 as Android's clamp16_from_float (HAL float capture to PCM_16BIT): round(x·32768), clamped. */
internal fun f32ToPcm16(x: Float): Short {
    if (x.isNaN()) return 0
    val v = round(x.toDouble() * 32768.0)
    return when {
        v >= 32767.0 -> Short.MAX_VALUE
        v <= -32768.0 -> Short.MIN_VALUE
        else -> v.toInt().toShort()
    }
}

/** Rate the session runs at, or null outside [SR_MIN, SR_MAX] (§4.2). */
internal fun sessionRate(hw: Double): Int? = round(hw).toInt().takeIf { it in PopConstants.SR_MIN..PopConstants.SR_MAX }

/**
 * Contract §4.2-§4.4 on iOS (decision note §4).
 *
 * Session: .playAndRecord, mode .measurement (no AGC / voice processing), .defaultToSpeaker, 48 kHz
 * preferred; whatever the hardware takes is reported as sample_rate. Voice processing stays off.
 *
 * Mic: inputNode tap (hardware format, channel 0) -> preallocated int16 buffer, placed by the
 * tap's sampleTime. Frame 0 = median over tap buffers after 0.5 s of hostTime − inputLatency −
 * frames·1e9/sr (fallback: min over callbacks of now − frames/sr).
 *
 * Speaker: AVAudioPlayerNode, one buffer PRIMER_S zeros ‖ play PCM, scheduled at the player
 * sample time of plan.playCallNs, so the §4.4 onset formula holds. Playback timestamp = last
 * lastRenderTime while or after playing: framePosition = player sample − scheduled start,
 * nanoTime = hostTime + outputLatency (fallback: host-time schedule, play call + latency).
 *
 * Interruption (call, Siri), route loss or engine reconfiguration aborts with capture_failed.
 * Host time == monoNanos (both mach_absolute_time).
 */
class IosAudioEngine : AudioEngine {
    private val session get() = AVAudioSession.sharedInstance()

    private var engine: AVAudioEngine? = null
    private var player: AVAudioPlayerNode? = null
    private var playBuf: AVAudioPCMBuffer? = null
    private var rec: Recorder? = null
    private var observers: List<NSObjectProtocol> = emptyList()
    private var sr = 0
    private var trackFrames = 0

    @Volatile private var failure: String? = null
    @Volatile private var drained = false

    private fun <T> nsCall(what: String, f: (kotlinx.cinterop.CPointer<ObjCObjectVar<NSError?>>) -> T): T = memScoped {
        val e = alloc<ObjCObjectVar<NSError?>>()
        val r = f(e.ptr)
        if (r == false) throw AudioException("capture_failed", "$what: ${e.value?.localizedDescription ?: "failed"}")
        r
    }

    /** Category + mode + rate, then active. Only with mic permission: activating a record category prompts. */
    private fun configureSession() {
        val s = session
        nsCall("setCategory") {
            s.setCategory(AVAudioSessionCategoryPlayAndRecord, AVAudioSessionModeMeasurement, AVAudioSessionCategoryOptionDefaultToSpeaker, it)
        }
        nsCall("setPreferredSampleRate") { s.setPreferredSampleRate(48000.0, it) }
        nsCall("setActive") { s.setActive(true, it) }
    }

    private fun outputLatencyMs(): Double = (session.outputLatency + session.IOBufferDuration) * 1000.0

    private fun externalOutput(): String? {
        val outs = session.currentRoute.outputs.filterIsInstance<AVAudioSessionPortDescription>()
        val d = outs.firstOrNull { it.portType != AVAudioSessionPortBuiltInSpeaker } ?: return null
        if (d.portType == AVAudioSessionPortBuiltInReceiver) return "the earpiece"
        return d.portName.takeIf { it.isNotBlank() } ?: "an external device"
    }

    override fun preflight(): AudioPreflight {
        val mic = hasMicPermission()
        val problems = mutableListOf<String>()
        val warnings = mutableListOf<String>()
        if (!mic) problems += "Microphone permission needed."
        val otherAudio = session.otherAudioPlaying
        if (mic && engine == null) {
            try {
                configureSession()
            } catch (e: AudioException) {
                problems += "Audio session unavailable (${e.message})."
            }
        }
        val s = session
        val hw = s.sampleRate
        val rate = sessionRate(hw)
        if (mic && rate == null) problems += "Audio runs at ${hw.toInt()} Hz; need ${PopConstants.SR_MIN}-${PopConstants.SR_MAX}."
        val volPct = round(s.outputVolume.toDouble() * 100).toInt()
        if (volPct < 60) problems += "Volume too low ($volPct%). Raise it with the side buttons to at least 60%."
        val ext = externalOutput()
        if (ext != null) problems += "Audio goes to $ext. Disconnect it so the phone speaker plays."
        val unp = s.mode == AVAudioSessionModeMeasurement
        if (mic && !unp) warnings += "Measurement mode not active; mic may be processed."
        val input = s.currentRoute.inputs.filterIsInstance<AVAudioSessionPortDescription>().firstOrNull()
        if (mic && input != null && input.portType != AVAudioSessionPortBuiltInMic) warnings += "Mic input is ${input.portName}, not the phone's mic."
        if (otherAudio) warnings += "Other audio is playing; stop it for a clean run."
        return AudioPreflight(rate ?: 48000, volPct, 100, ext, mic, unp, outputLatencyMs(), problems, warnings)
    }

    /** iOS has no public API to set the output volume; the user uses the side buttons. */
    override fun setMediaVolume(frac: Double) {}

    override fun prepare(sr: Int, play: FloatArray) {
        release()
        if (!hasMicPermission()) throw AudioException("capture_failed", "no microphone permission")
        require(sr in PopConstants.SR_MIN..PopConstants.SR_MAX) { "sr $sr" }
        this.sr = sr
        failure = null
        drained = false
        try {
            configureSession()
            observe()
            open(sr, play)
        } catch (e: Throwable) {
            release()
            if (e is AudioException) throw e
            throw AudioException("capture_failed", "audio open: ${e.message}")
        }
    }

    private fun open(sr: Int, play: FloatArray) {
        val e = AVAudioEngine()
        engine = e
        val input = e.inputNode
        val inFmt = input.outputFormatForBus(0u)
        if (round(inFmt.sampleRate).toInt() != sr) throw AudioException("capture_failed", "mic runs at ${inFmt.sampleRate}, wanted $sr")
        if (inFmt.channelCount < 1u) throw AudioException("capture_failed", "mic has no channels")

        val fmt = AVAudioFormat(standardFormatWithSampleRate = sr.toDouble(), channels = 1u)
        val primer = AudioTiming.primerFrames(sr)
        val n = primer + play.size
        val buf = AVAudioPCMBuffer(pCMFormat = fmt, frameCapacity = n.toUInt())
            ?: throw AudioException("capture_failed", "AVAudioPCMBuffer($n)")
        val ch = buf.floatChannelData?.get(0) ?: throw AudioException("capture_failed", "play buffer has no data")
        for (i in 0 until primer) ch[i] = 0f
        for (i in play.indices) ch[primer + i] = play[i]
        buf.frameLength = n.toUInt()
        playBuf = buf
        trackFrames = n

        val p = AVAudioPlayerNode()
        player = p
        e.attachNode(p)
        e.connect(p, e.mainMixerNode, fmt)

        // rec start .. stop + margin, allocated once here
        val r = Recorder(sr, ((RunPlan.REC_POST_NS + RunPlan.REC_PRE_NS) / 1e9 * sr + 2.0 * sr).toInt(),
            round(session.inputLatency * 1e9).toLong())
        rec = r
        input.installTapOnBus(0u, (sr / 10).toUInt(), inFmt) { b, t -> if (b != null) r.onBuffer(b, t) }

        e.prepare()
        nsCall("engine start") { e.startAndReturnError(it) }
        p.play() // renders silence until the scheduled buffer; output path is running well before t0
    }

    private fun observe() {
        val nc = NSNotificationCenter.defaultCenter
        val s = session
        observers = listOf(
            nc.addObserverForName(AVAudioSessionInterruptionNotification, s, null) { n: NSNotification? ->
                val type = (n?.userInfo?.get(AVAudioSessionInterruptionTypeKey) as? NSNumber)?.unsignedLongValue
                if (type == AVAudioSessionInterruptionTypeBegan) fail("audio interrupted (call?)")
            },
            nc.addObserverForName(AVAudioSessionRouteChangeNotification, s, null) { n: NSNotification? ->
                val why = (n?.userInfo?.get(AVAudioSessionRouteChangeReasonKey) as? NSNumber)?.unsignedLongValue
                if (why == AVAudioSessionRouteChangeReasonNewDeviceAvailable || why == AVAudioSessionRouteChangeReasonOldDeviceUnavailable) {
                    fail("audio route changed")
                }
            },
            nc.addObserverForName(AVAudioSessionMediaServicesWereResetNotification, s, null) { _: NSNotification? ->
                fail("media services reset")
            },
            nc.addObserverForName(AVAudioEngineConfigurationChangeNotification, null, null) { n: NSNotification? ->
                if (n?.`object` === engine) fail("audio configuration changed")
            },
        )
    }

    private fun fail(why: String) {
        if (failure == null) failure = why
    }

    private fun checkFailure() {
        failure?.let { throw AudioException("capture_failed", it) }
        if (engine?.running != true) throw AudioException("capture_failed", "audio engine stopped")
    }

    override suspend fun run(plan: RunPlan): Capture = withContext(Dispatchers.Default) {
        val r = rec ?: throw AudioException("capture_failed", "not prepared")
        val p = player ?: throw AudioException("capture_failed", "not prepared")
        val buf = playBuf ?: throw AudioException("capture_failed", "not prepared")
        check(plan.sr == sr) { "plan sr ${plan.sr} != prepared $sr" }
        checkFailure()
        try {
            record(r, p, buf, plan)
        } finally {
            r.armed = false
        }
    }

    /** Player (sample, host ns) of the latest render, or null before the first render. */
    private fun playerNow(p: AVAudioPlayerNode): Pair<Long, Long>? {
        val nt = p.lastRenderTime ?: return null
        if (!nt.sampleTimeValid || !nt.hostTimeValid) return null
        val pt = p.playerTimeForNodeTime(nt) ?: return null
        if (!pt.sampleTimeValid) return null
        return pt.sampleTime to HostClock.toNs(nt.hostTime)
    }

    private suspend fun record(r: Recorder, p: AVAudioPlayerNode, buf: AVAudioPCMBuffer, plan: RunPlan): Capture {
        waitUntil(plan.recStartNs)
        checkFailure()
        r.armed = true

        // schedule primer ‖ play so its frame 0 renders at plan.playCallNs
        val now0 = playerNow(p)
        val start: Long?
        val calledNs = monoNanos()
        var lateMs = 0.0
        val whenT = if (now0 != null) {
            val s = now0.first + round((plan.playCallNs - now0.second) * sr / 1e9).toLong()
            start = s
            if (s <= now0.first) lateMs = (now0.first - s) * 1000.0 / sr
            AVAudioTime(hostTime = HostClock.toHost(plan.playCallNs), sampleTime = s, atRate = sr.toDouble())
        } else {
            start = null
            lateMs = maxOf(0.0, (calledNs - plan.playCallNs) / 1e6)
            AVAudioTime(hostTime = HostClock.toHost(plan.playCallNs))
        }
        p.scheduleBuffer(buf, whenT, 0u, AVAudioPlayerNodeCompletionDataPlayedBack) { _ -> drained = true }

        var ts: Pair<Long, Long>? = null
        val playEnd = plan.playCallNs + (trackFrames * 1e9 / sr).toLong() + 1_000_000_000L
        val hardStop = plan.stopNs + 1_500_000_000L
        while (true) {
            delay(10)
            checkFailure()
            val now = monoNanos()
            if (start != null) playerNow(p)?.let { (ps, h) -> if (ps > start) ts = (ps - start) to h }
            val playerDone = drained || now >= playEnd
            if (now >= plan.stopNs + 100_000_000L && playerDone) {
                val (pos, f0) = r.snapshot()
                if (f0 != null && pos >= AudioTiming.captureStartFrame(plan.captureStartNs, f0, sr) + plan.captureFrames) break
                if (now >= hardStop) break
            }
            if (now >= hardStop + 1_000_000_000L) break
        }
        r.armed = false
        if (start != null) playerNow(p)?.let { (ps, h) -> if (ps > start) ts = (ps - start) to h } // after drain (§4.4)

        val (pos, f0Est) = r.snapshot()
        val recTsSource = if (r.estimateCount() > 0) "audiotimestamp" else "fallback"
        val f0 = f0Est ?: throw AudioException("capture_failed", "no mic frames")
        val spreadUs = r.spreadUs()
        val cs = AudioTiming.captureStartFrame(plan.captureStartNs, f0, sr)
        val frames = plan.captureFrames
        if (cs < 0 || cs + frames > pos) {
            throw AudioException("capture_failed", "capture [$cs, ${cs + frames}) outside recorded [0, $pos)")
        }
        val pcm = r.copy(cs.toInt(), frames)
        val frame0 = round(f0 + cs * 1e9 / sr).toLong()

        val latency = outputLatencyMs()
        val latNs = round(latency * 1e6).toLong()
        val t = ts
        val (pos0, nano0, src) = if (t != null) Triple(t.first, t.second + latNs, "audiotimestamp")
        else Triple(0L, plan.playCallNs + latNs, "fallback")
        println("PopAudio rec f0=$recTsSource spread=${round(spreadUs * 10) / 10}us gaps=${r.gaps} " +
            "play ts=$src pos=$pos0 late=${round(lateMs * 100) / 100}ms drained=$drained")
        return Capture(
            pcm = pcm, sr = sr, recFrame0NanoTime = frame0,
            playFramePosition = pos0, playNanoTime = nano0, tsSource = src, recTsSource = recTsSource,
            outputLatencyMs = latency, micSource = if (session.mode == AVAudioSessionModeMeasurement) "measurement" else "default",
            effectsOff = emptyList(), playLateMs = lateMs, recTsSpreadUs = spreadUs, framesRecorded = pos.toLong(),
            captureStartFrame = cs, trackDrained = drained,
        )
    }

    override fun release() {
        val nc = NSNotificationCenter.defaultCenter
        observers.forEach { nc.removeObserver(it) }
        observers = emptyList()
        rec?.armed = false
        engine?.let { e ->
            runCatching { e.inputNode.removeTapOnBus(0u) }
            runCatching { player?.stop() }
            runCatching { e.stop() }
            player?.let { runCatching { e.detachNode(it) } }
            runCatching {
                memScoped {
                    val err = alloc<ObjCObjectVar<NSError?>>()
                    session.setActive(false, AVAudioSessionSetActiveOptionNotifyOthersOnDeactivation, err.ptr)
                }
            }
        }
        engine = null
        player = null
        playBuf = null
        rec = null
    }
}

/**
 * Tap sink, called on the tap thread. Frames go to [buf] at (sampleTime − first sampleTime), so a
 * dropped tap buffer leaves zeros instead of shifting the rest.
 */
private class Recorder(val sr: Int, size: Int, val inputLatencyNs: Long) {
    private val lock = NSLock()
    private val buf = ShortArray(size)
    private var st0 = -1L
    private var pos = 0
    private var seqPos = 0
    private val estimates = ArrayList<Double>()
    private var fallback0 = Double.MAX_VALUE
    var gaps = 0
        private set

    @Volatile var armed = false

    fun onBuffer(b: AVAudioPCMBuffer, t: AVAudioTime?) {
        if (!armed) return
        val n = b.frameLength.toInt()
        val data = b.floatChannelData?.get(0) ?: return
        val stride = b.stride.toInt().coerceAtLeast(1)
        val now = monoNanos()
        lock.lock()
        try {
            val at = if (t != null && t.sampleTimeValid) {
                if (st0 < 0) st0 = t.sampleTime
                (t.sampleTime - st0).toInt()
            } else seqPos
            if (at < 0) return
            if (at > seqPos) gaps++
            val m = minOf(n, buf.size - at)
            for (i in 0 until m) buf[at + i] = f32ToPcm16(data[i * stride])
            seqPos = maxOf(seqPos, at + maxOf(m, 0))
            pos = seqPos
            fallback0 = minOf(fallback0, now - pos * 1e9 / sr)
            if (t != null && t.hostTimeValid && t.sampleTimeValid && at >= sr / 2) {
                estimates += HostClock.toNs(t.hostTime) - inputLatencyNs - at * 1e9 / sr
            }
        } finally {
            lock.unlock()
        }
    }

    /** (frames recorded, frame-0 estimate or null). */
    fun snapshot(): Pair<Int, Double?> {
        lock.lock()
        try {
            val f0 = if (estimates.isNotEmpty()) AudioTiming.median(estimates) else fallback0.takeIf { pos > 0 }
            return pos to f0
        } finally {
            lock.unlock()
        }
    }

    fun estimateCount(): Int {
        lock.lock()
        try { return estimates.size } finally { lock.unlock() }
    }

    fun spreadUs(): Double {
        lock.lock()
        try { return if (estimates.size > 1) (estimates.max() - estimates.min()) / 1e3 else 0.0 } finally { lock.unlock() }
    }

    fun copy(from: Int, n: Int): ShortArray {
        lock.lock()
        try { return buf.copyOfRange(from, from + n) } finally { lock.unlock() }
    }
}

/** Coarse delay to ~2 ms before [targetNs]; only the recording gate uses it, the play is sample-scheduled. */
private suspend fun waitUntil(targetNs: Long) {
    while (true) {
        val d = targetNs - monoNanos()
        if (d <= 0) return
        delay(maxOf(1L, (d - 2_000_000L) / 1_000_000L))
    }
}
