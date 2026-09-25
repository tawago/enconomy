package com.enconomy.pop

import com.enconomy.pop.dsp.Arrival
import com.enconomy.pop.dsp.PopDsp
import com.enconomy.pop.dsp.PopRound
import io.ktor.client.network.sockets.SocketTimeoutException
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.http.ContentType
import io.ktor.http.HttpMethod
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** §9.2 phone states from Arming on. */
enum class RunPhase { Arming, Running, SelfCheck, Committing, Measuring, Submitting, Failing, WaitingResult }

/** Pre-flight / clock refused before arm. Nothing sent; the user fixes it and taps Start again. */
class RunBlocked(msg: String) : Exception(msg)

/** §8.3 user text. */
object Reasons {
    val text = mapOf(
        "too_far" to "Too far apart. Hold the phones side by side.",
        "partner_not_heard" to "Partner not heard. Check volume and try again.",
        "self_not_heard" to "Your own sound was not heard. Check volume and mic.",
        "glitch" to "Recording glitch, trying again.",
        "impossible_flight" to "Measurement failed, trying again.",
        "self_timestamp_mismatch" to "Audio timing off, trying again.",
        "capture_failed" to "Audio capture failed, trying again.",
        "timeout" to "Partner did not finish in time.",
        "signature_invalid" to "Device signature invalid.",
        "transcript_mismatch" to "Session data mismatch.",
        "partner_mismatch" to "Invite does not match this partner.",
        "aborted" to "Session aborted.",
    )

    fun of(reason: String?): String? = reason?.let { text[it] ?: it }
}

/**
 * One confirmed session, from arm to result (contract §4-§8, §9.2 Arming..WaitingResult).
 *
 * Per attempt: preflight -> clock sync -> arm (own play + own bed) -> prepare audio -> poll t0 ->
 * record + play -> self check (§6.6 1-4) -> signed commit -> partner bed -> partner arrival ->
 * signed transcript -> optional recording upload -> poll. A failed step posts /fail.
 * Retry is server driven: the view going back to `confirmed` with attempt + 1 re-arms (§8.2),
 * so at most one automatic retry, and only for measurement failures.
 *
 * Choices the contract leaves open:
 *  - a 409 on commit/transcript/fail means the partner already moved the session on
 *    (its fail, a retry, done); the phone stops that attempt and follows the view.
 *  - 409 too_early on commit (clock skew) is retried every 250 ms for up to 3 s.
 *  - waiting for the partner to arm: 120 s, then abort.
 *  - null templates for self and partner are built while waiting for t0.
 */
class PopRun(
    private val api: PopApi,
    private val engine: AudioEngine,
    private val key: DeviceKey,
    private val sessionId: String,
    private val role: Char,
    private val uploadRecordings: Boolean = true,
    private val onStatus: (RunPhase, Int, String?) -> Unit = { _, _, _ -> },
    private val clock: suspend () -> ClockOffset = { ClockSync.measure(api) },
    private val nowNs: () -> Long = ::monoNanos,
    private val model: String = "",
) {
    private val partnerRole = if (role == 'A') 'B' else 'A'

    /** Runs until the session is done or aborted. Throws RunBlocked before arming. */
    suspend fun run(): ResultRecord {
        var v = api.session(sessionId)
        while (true) {
            v = when (v.state) {
                "done" -> return resultOf(v)
                "aborted" -> return aborted(v.error)
                "confirmed" -> attempt(v)
                else -> waitNext(v, v.attempt)
            }
        }
    }

    private fun status(p: RunPhase, attempt: Int, note: String? = null) = onStatus(p, attempt, note)

    private suspend fun resultOf(v: SessionView): ResultRecord =
        v.result?.let { popJson.decodeFromJsonElement(ResultRecord.serializer(), it) } ?: api.result(sessionId)

    private fun aborted(reason: String?) = ResultRecord(session_id = sessionId, verdict = "NOT_NEAR", reason = reason ?: "aborted")

    // ---- one attempt ----

    private suspend fun attempt(v0: SessionView): SessionView {
        val k = v0.attempt
        check(k < PopConstants.MAX_ATTEMPTS) { "attempt $k" }
        val retryNote = v0.last_failure?.takeIf { k > 0 }?.let { it.text ?: Reasons.of(it.reason) }
        status(RunPhase.Arming, k, retryNote)
        val nonce = v0.nonce?.hexToBytes() ?: error("no session nonce")
        val pkPartner = v0.partner?.pubkey?.hexToBytes() ?: error("no partner pubkey")
        check(nonce.size == 32 && pkPartner.size == 65) { "bad nonce / partner key" }

        val pre = engine.preflight()
        if (!pre.ok) throw RunBlocked(pre.problems.joinToString("\n"))
        val clk = clock()
        if (!clk.ok) throw RunBlocked("Network too slow (rtt ${clk.rttMinMs.toInt()} ms). Move closer to Wi-Fi and try again.")
        val sr = pre.sampleRate

        val arm = api.arm(sessionId, ArmReq(k, sr, clk.rttMinMs))
        check(arm.attempt == k && arm.sample_rate == sr) { "arm echo ${arm.attempt}/${arm.sample_rate} != $k/$sr" }
        val cap: Capture
        val plan: RunPlan
        try {
            val play = arm.play.decodeF32(sr)
            val ownBed = arm.own_bed.decodeF64(sr)
            engine.prepare(sr, play)
            val started = coroutineScope {
                val nulls = async(Dispatchers.Default) {
                    PopDsp.nullTemplates(sessionId, role, k, sr); PopDsp.nullTemplates(sessionId, partnerRole, k, sr)
                }
                status(RunPhase.Arming, k, retryNote ?: "waiting for partner")
                val s = poll(v0.seq, nowNs() + 120_000_000_000L) { it.attempt != k || it.t0_ms != null || it.state !in LIVE }
                nulls.await()
                s
            }
            if (started == null) {
                runCatching { api.abort(sessionId) }
                return api.session(sessionId)
            }
            if (started.attempt != k || started.t0_ms == null) return started
            plan = RunPlan.of(role, sr, started.t0_ms, clk)
            if (plan.recStartNs <= nowNs()) throw AudioException("capture_failed", "t0 already passed")
            status(RunPhase.Running, k)
            cap = engine.run(plan)
            return afterCapture(k, nonce, pkPartner, plan, cap, ownBed)
        } catch (e: AudioException) {
            engine.release()
            return fail(k, e.reason, buildJsonObject { put("error", e.message) })
        } finally {
            engine.release()
        }
    }

    private suspend fun afterCapture(k: Int, nonce: ByteArray, pkPartner: ByteArray, plan: RunPlan, cap: Capture,
                                     ownBed: DoubleArray): SessionView {
        engine.release() // mic + speaker off once Running is over (§9.2)
        val sr = plan.sr
        status(RunPhase.SelfCheck, k)
        val r = PopRound(cap.pcm, sr, role, sessionId, k)
        val expSelf = cap.expectedSelf()
        val self = withContext(Dispatchers.Default) { r.selfCheck(ownBed, expSelf) }
        if (self !is PopRound.Step.SelfOk) {
            val f = self as PopRound.Step.Failed
            return fail(k, f.reason, meta(cap, r, expSelf, null, null))
        }

        status(RunPhase.Committing, k)
        val commit = TranscriptCodec.commit(role, k, nonce, r.recSha256)
        val commitSig = sign(commit)
        val bed = try {
            commitWithRetry(CommitReq(commit.toB64(), commitSig.toB64()))
        } catch (e: PopHttpException) {
            if (e.status == 409) return waitNext(null, k)
            throw e
        }

        status(RunPhase.Measuring, k)
        val partnerBed = bed.partner_bed.decodeF64(sr)
        val expPartner = cap.expectedPartner(plan)
        val p = withContext(Dispatchers.Default) { r.measurePartner(partnerBed, expPartner) }
        if (p !is PopRound.Step.PartnerOk) {
            return fail(k, (p as PopRound.Step.Failed).reason, meta(cap, r, expSelf, expPartner, null))
        }

        status(RunPhase.Submitting, k)
        val t = Transcript(
            role = role, attempt = k, sessionNonce = nonce, pkSelf = key.pubkey, pkPartner = pkPartner,
            sampleRate = sr, half = p.half, recSha256 = r.recSha256,
            playFramePosition = cap.playFramePosition, playNanoTime = cap.playNanoTime,
            recFrame0NanoTime = cap.recFrame0NanoTime, selfOsDelta = self.selfOsDelta,
            commitHash = sha256(commit),
        )
        val tx = t.encode()
        val sig = sign(tx)
        try {
            api.transcript(sessionId, TranscriptReq(tx.toB64(), sig.toB64(), meta(cap, r, expSelf, expPartner, p.half)))
        } catch (e: PopHttpException) {
            // 409: partner moved on; 400: server rejected and finalized. Either way the view says what happened.
            if (e.status != 409 && e.status != 400) throw e
        }
        if (uploadRecordings) upload(k, cap)
        return waitNext(null, k)
    }

    private suspend fun sign(msg: ByteArray): ByteArray = withContext(Dispatchers.Default) { key.sign(msg) }

    private suspend fun commitWithRetry(req: CommitReq): CommitResp {
        var tries = 0
        while (true) {
            try {
                return api.commit(sessionId, req)
            } catch (e: PopHttpException) {
                if (e.code != "too_early" || ++tries > 12) throw e
                delay(250)
            }
        }
    }

    private suspend fun fail(k: Int, reason: String, meta: JsonObject?): SessionView {
        status(RunPhase.Failing, k, Reasons.of(reason))
        try {
            api.fail(sessionId, k, reason)
        } catch (e: PopHttpException) {
            if (e.status != 409 && e.status != 400) throw e
        }
        return waitNext(null, k)
    }

    /** Poll until done/aborted or the server moved to a later attempt. */
    private suspend fun waitNext(v: SessionView?, k: Int): SessionView {
        status(RunPhase.WaitingResult, k)
        val deadline = nowNs() + (PopConstants.TRANSCRIPT_DEADLINE_S + 40) * 1_000_000_000L
        val out = poll(v?.seq, deadline) { it.state == "done" || it.state == "aborted" || it.attempt > k }
        return out ?: run {
            runCatching { api.abort(sessionId) }
            api.session(sessionId)
        }
    }

    /** Long-poll until [done] or [deadlineNs]; null on deadline. */
    private suspend fun poll(after: Long?, deadlineNs: Long, done: (SessionView) -> Boolean): SessionView? {
        var seq = after
        var misses = 0
        while (true) {
            val left = (deadlineNs - nowNs()) / 1_000_000L
            if (left <= 0) return null
            val v = try {
                api.session(sessionId, after = seq ?: -1, timeoutS = (left / 1000).coerceIn(1, 25).toInt())
            } catch (e: HttpRequestTimeoutException) {
                if (++misses > 3) throw e
                delay(300); continue
            } catch (e: SocketTimeoutException) {
                if (++misses > 3) throw e
                delay(300); continue
            }
            misses = 0
            seq = v.seq
            if (done(v) || v.state !in LIVE) return v
        }
    }

    private suspend fun upload(k: Int, cap: Capture) {
        try {
            val boundary = "pop" + sha256(cap.recSha256).toHex().take(24)
            val m = buildJsonObject { put("attempt", k); put("role", role.toString()); put("sample_rate", cap.sr) }
            val body = Multipart.formData(boundary, listOf(
                Multipart.Part("wav", "capture_${role}_$k.wav", "audio/wav", Wav.pcm16Mono(cap.pcm, cap.sr)),
                Multipart.Part("meta", null, null, m.toString().encodeToByteArray()),
            ))
            api.signedRaw(HttpMethod.Post, "/v1/session/$sessionId/recording", body,
                ContentType.MultiPart.FormData.withParameter("boundary", boundary))
        } catch (e: CancellationException) {
            throw e
        } catch (_: Throwable) {
            // diagnostics only
        }
    }

    /** §7.1 meta: unsigned diagnostics. */
    private fun meta(cap: Capture, r: PopRound, expSelf: Double, expPartner: Double?, half: Int?): JsonObject = buildJsonObject {
        cap.meta().forEach { (k, v) -> put(k, v) }
        put("role", role.toString())
        put("expected_self", expSelf)
        expPartner?.let { put("expected_partner", it) }
        arrival("self", r.self)
        arrival("partner", r.partner)
        half?.let { put("half", it) }
        put("flat_runs", JsonArray(r.flatRuns.map { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.last + 1))) }))
        put("security_level", key.securityLevel)
        put("model", model)
    }

    private fun kotlinx.serialization.json.JsonObjectBuilder.arrival(name: String, a: Arrival?) {
        if (a == null) return
        put("t_$name", a.frame)
        put("score_$name", a.score)
        put("bar_$name", a.bar)
        put("null_max_$name", a.nullMax)
        put("strongest_$name", a.strongestFrame)
        put("strongest_score_$name", a.strongestScore)
        a.why?.let { put("why_$name", it) }
    }

    companion object {
        val LIVE = setOf("created", "joined", "confirmed", "started")
    }
}

/** int16 mono WAV (recording upload, §9). Frames are the capture bytes, so sha256 matches rec_sha256. */
object Wav {
    fun pcm16Mono(pcm: ShortArray, sr: Int): ByteArray {
        val data = AudioTiming.pcm16Le(pcm)
        val h = ByteArray(44)
        fun s(o: Int, t: String) = t.encodeToByteArray().copyInto(h, o)
        fun le(o: Int, v: Long, n: Int) { for (i in 0 until n) h[o + i] = (v ushr (8 * i)).toByte() }
        s(0, "RIFF"); le(4, 36L + data.size, 4); s(8, "WAVE")
        s(12, "fmt "); le(16, 16, 4); le(20, 1, 2); le(22, 1, 2); le(24, sr.toLong(), 4); le(28, 2L * sr, 4); le(32, 2, 2); le(34, 16, 2)
        s(36, "data"); le(40, data.size.toLong(), 4)
        return h + data
    }
}

object Multipart {
    class Part(val name: String, val filename: String?, val contentType: String?, val body: ByteArray)

    fun formData(boundary: String, parts: List<Part>): ByteArray {
        val out = ArrayList<ByteArray>()
        for (p in parts) {
            val sb = StringBuilder("--$boundary\r\nContent-Disposition: form-data; name=\"${p.name}\"")
            if (p.filename != null) sb.append("; filename=\"${p.filename}\"")
            sb.append("\r\n")
            if (p.contentType != null) sb.append("Content-Type: ${p.contentType}\r\n")
            sb.append("\r\n")
            out += sb.toString().encodeToByteArray(); out += p.body; out += "\r\n".encodeToByteArray()
        }
        out += "--$boundary--\r\n".encodeToByteArray()
        val n = out.sumOf { it.size }
        val b = ByteArray(n)
        var i = 0
        for (x in out) { x.copyInto(b, i); i += x.size }
        return b
    }
}
