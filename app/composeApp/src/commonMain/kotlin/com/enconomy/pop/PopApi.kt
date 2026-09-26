@file:OptIn(ExperimentalSerializationApi::class)

package com.enconomy.pop

import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.timeout
import io.ktor.client.request.header
import io.ktor.client.request.prepareRequest
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.HttpHeaders
import io.ktor.utils.io.readAvailable
import io.ktor.client.request.headers
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpMethod
import io.ktor.http.Url
import io.ktor.http.content.ByteArrayContent
import io.ktor.http.isSuccess
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.EncodeDefault
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

// ---- wire types, docs/pop-contract.md §2-§9 ----

@Serializable data class TimeResp(val server_ms: Long)
@Serializable data class NonceResp(val nonce: String, val expires_at_ms: Long? = null)

@Serializable
data class EnrollReq(
    val nonce: String,
    val device_id: String,
    val pubkey: String,
    val display_name: String,
    val model: String,
    val security_level: String,
    val chain: List<String>?,
    /** §2.2.1: "ios" sends key_kind + app_attest, chain = null. */
    val platform: String = "android",
    val key_kind: String? = null,
    val app_attest: AppAttestReq? = null,
    /** SBcred3: Poseidon7(holder secret), 64 hex. Omitted for a server without an issuer (v1 enroll). */
    @EncodeDefault(EncodeDefault.Mode.NEVER) val holder_commit: String? = null,
)

/** base64 std both. */
@Serializable data class AppAttestReq(val key_id: String, val attestation: String)

@Serializable
data class EnrollResp(
    val device_id: String,
    val attested: Boolean = false,
    val enrolled_at: JsonElement? = null,
    val credential: CredentialResp? = null,
)

/** Issued when holder_commit was sent. cred/sig base64 std; sig raw r||s; issuer_pubkey 65 hex. */
@Serializable
data class CredentialResp(
    val format: String,
    val cred_b64: String,
    val sig_b64: String,
    val expiry: Long,
    val issuer_pubkey: String? = null,
)

/** /v1/config "issuer".pubkey (65 bytes), null when the server issues no credentials. */
fun issuerPubkeyOf(cfg: JsonObject): ByteArray? {
    val iss = cfg["issuer"] as? JsonObject ?: return null
    val hex = (iss["pubkey"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
    return runCatching { hex.hexToBytes() }.getOrNull()?.takeIf { it.size == 65 && it[0] == 4.toByte() }
}

@Serializable
data class CreateSessionResp(
    val session_id: String,
    val join_token: String,
    val expires_at_ms: Long,
    val invite_b64url: String? = null,
    // docs/worldid/01 §9 row 1: present when created with a context (PopCtx nonce)
    val nonce: String? = null,
    val not_before: Long? = null,
    val context: JsonObject? = null,
    val policy: JsonObject? = null,
)

/** docs/worldid/01 §9 row 1. Both null = the old `{}` body. */
@Serializable data class SessionReq(val context: JsonObject? = null, val policy: JsonObject? = null) {
    /** Absent fields are left out (not null), so no context still sends exactly `{}`. */
    fun body(): String = JsonObject(listOfNotNull(context?.let { "context" to it }, policy?.let { "policy" to it }).toMap()).toString()
}

@Serializable data class JoinReq(val join_token: String)
@Serializable data class DeviceRef(val device_id: String, val display_name: String? = null)

@Serializable
data class PartnerView(
    val device_id: String,
    val display_name: String? = null,
    val model: String? = null,
    val attested: Boolean = false,
    val pubkey: String? = null,
)

@Serializable
data class SessionView(
    val session_id: String,
    val seq: Long = 0,
    val state: String,
    val attempt: Int = 0,
    val role: String? = null,
    val nonce: String? = null,
    val self: DeviceRef? = null,
    val partner: PartnerView? = null,
    val confirmed: Map<String, Boolean> = emptyMap(),
    val armed: Map<String, Boolean> = emptyMap(),
    val committed: Map<String, Boolean> = emptyMap(),
    val submitted: Map<String, Boolean> = emptyMap(),
    val t0_ms: Long? = null,
    val constants: JsonObject? = null,
    val result: JsonObject? = null,
    val error: String? = null,
    /** Server extra: why the previous attempt failed (shown while re-arming). */
    val last_failure: Failure? = null,
    // docs/worldid/01 §9 row 3
    val context: JsonObject? = null,
    val not_before: Long? = null,
    val policy: JsonObject? = null,
    val human: JsonObject? = null,
)

@Serializable data class Failure(val attempt: Int = 0, val reason: String? = null, val by: String? = null, val text: String? = null)

/** §8.4, the fields the phone shows. */
@Serializable
data class ResultRecord(
    val session_id: String? = null,
    val attempt: Int = 0,
    val verdict: String,
    val reason: String? = null,
    val user_text: String? = null,
    val flight_cm: Double? = null,
    val t0_ms: Long? = null,
    val attempts: List<JsonObject> = emptyList(),
    /** Option A validAt (unix s) when the server pins one; the phone falls back to t0 of the attempt. */
    val valid_at: Long? = null,
    // docs/worldid/01 §9 row 8
    val context: JsonObject? = null,
    val not_before: Long? = null,
    val human: JsonObject? = null,
    val pair_tag: String? = null,
)

/** POST /v1/session/{sid}/worldid/start (docs/worldid/01 §9 row 4). */
@Serializable data class WorldIdStartResp(val request_id: String? = null, val connector_uri: String, val expires_at_s: Long? = null)

/** GET /v1/session/{sid}/worldid (§9 row 5), the caller's role. */
@Serializable
data class WorldIdStatusResp(
    val role: String? = null,
    val status: String,
    val error: String? = null,
    /** Server extras: partner {status}, and the live request while pending. */
    val partner: JsonObject? = null,
    val pair_tag: String? = null,
    val connector_uri: String? = null,
    val expires_at_s: Long? = null,
)

@Serializable data class Pcm(val pcm_b64: String, val n: Int)
/** [popt] 2 = POPT v2 for this role and attempt; null (not sent) = pop-v1. */
@Serializable
data class ArmReq(
    val attempt: Int,
    val sample_rate: Int,
    val rtt_min_ms: Double,
    @EncodeDefault(EncodeDefault.Mode.NEVER) val popt: Int? = null,
)

/** v2 adds popt, own_code (int8 at our sr) and delta. */
@Serializable
data class ArmResp(
    val attempt: Int,
    val sample_rate: Int,
    val play: Pcm,
    val own_bed: Pcm,
    val popt: Int? = null,
    val own_code: CodeWire? = null,
    val delta: Int? = null,
)

/** int8 cI / cQ, base64 std, n values each (docs/pop-transcript-v2.md §3). */
@Serializable data class CodeWire(val cI_b64: String, val cQ_b64: String, val n: Int)

@Serializable data class CommitReq(val commit_b64: String, val sig_b64: String)
/** v2 adds partner_code (released only after the POPC v2 commit). */
@Serializable data class CommitResp(val partner_bed: Pcm, val partner_code: CodeWire? = null)
@Serializable data class TranscriptReq(val transcript_b64: String, val sig_b64: String, val meta: JsonObject)
@Serializable data class TranscriptResp(val accepted: Boolean, val state: String? = null)
@Serializable data class FailReq(val attempt: Int, val reason: String)
@Serializable class Empty

/** Non-2xx. [code] = `error` field of the body when present; [hint] = user-facing text, when there is one. */
class PopHttpException(val status: Int, val code: String?, val body: String, val hint: String? = null) :
    Exception(hint ?: "HTTP $status ${code ?: ""}: ${body.take(300)}")

const val CLOCK_OFF_TEXT = "Phone clock is off; set automatic time."

val popJson = Json { ignoreUnknownKeys = true; encodeDefaults = true; explicitNulls = true }

/**
 * Contract API client. [key] signs every call after enroll (§2.3).
 * Signed path = URL encoded path + query as sent (includes any prefix in [baseUrl]).
 *
 * X-Pop-Ts = [nowMs] + server offset. The offset comes from one GET /v1/time before the first
 * signed call (midpoint of the request rtt) and again on auth_stale, then the call is re-sent once.
 * Still stale after that = the phone clock is off by more than the server allows: [CLOCK_OFF_TEXT].
 * [clockSync] = false signs with the raw wall clock (no /v1/time).
 */
class PopApi(
    baseUrl: String,
    private val key: () -> DeviceKey? = { null },
    private val nowMs: () -> Long = ::unixMs,
    engine: HttpClientEngine? = null,
    private val clockSync: Boolean = true,
) {
    val base = baseUrl.trim().trimEnd('/')

    private val cfg: HttpClientConfig<*>.() -> Unit = {
        install(HttpTimeout) {
            requestTimeoutMillis = 40_000 // long-poll is 25 s
            socketTimeoutMillis = 40_000 // okhttp default readTimeout is 10 s; server holds long-polls idle
            connectTimeoutMillis = 10_000
        }
        expectSuccess = false
    }
    private val client = if (engine != null) HttpClient(engine, cfg) else HttpClient(cfg)

    /** server_ms − local wall ms; null = not synced yet. */
    var clockOffsetMs: Long? = null
        private set
    private val clockLock = Mutex()

    /** GET /v1/time; offset = server_ms − midpoint(send, receive). */
    suspend fun syncClock(): Long {
        val t0 = nowMs()
        val s = time().server_ms
        val t1 = nowMs()
        return (s - (t0 + (t1 - t0) / 2)).also { clockOffsetMs = it }
    }

    private suspend fun offset(): Long {
        if (!clockSync) return 0
        clockOffsetMs?.let { return it }
        return clockLock.withLock { clockOffsetMs ?: syncClock() }
    }

    // ---- unsigned ----
    suspend fun time(): TimeResp = call(HttpMethod.Get, "/v1/time", null, TimeResp.serializer(), signed = false)
    suspend fun config(): JsonObject = call(HttpMethod.Get, "/v1/config", null, JsonObject.serializer(), signed = false)
    suspend fun enrollNonce(): NonceResp = call(HttpMethod.Get, "/v1/enroll/nonce", null, NonceResp.serializer(), signed = false)
    suspend fun enroll(req: EnrollReq): EnrollResp =
        call(HttpMethod.Post, "/v1/enroll", enc(EnrollReq.serializer(), req), EnrollResp.serializer(), signed = false)

    // ---- signed ----
    suspend fun createSession(req: SessionReq = SessionReq()): CreateSessionResp =
        call(HttpMethod.Post, "/v1/session", req.body(), CreateSessionResp.serializer())

    suspend fun join(id: String, joinToken: String): SessionView =
        call(HttpMethod.Post, "/v1/session/$id/join", enc(JoinReq.serializer(), JoinReq(joinToken)), SessionView.serializer())

    /** Long-poll: returns when seq > [after] or after [timeoutS]. */
    suspend fun session(id: String, after: Long? = null, timeoutS: Int? = null): SessionView {
        val q = listOfNotNull(after?.let { "after=$it" }, timeoutS?.let { "timeout_s=$it" }).joinToString("&")
        return call(HttpMethod.Get, "/v1/session/$id" + (if (q.isEmpty()) "" else "?$q"), null, SessionView.serializer())
    }

    suspend fun confirm(id: String): SessionView = call(HttpMethod.Post, "/v1/session/$id/confirm", "{}", SessionView.serializer())
    suspend fun arm(id: String, req: ArmReq): ArmResp =
        call(HttpMethod.Post, "/v1/session/$id/arm", enc(ArmReq.serializer(), req), ArmResp.serializer())
    suspend fun commit(id: String, req: CommitReq): CommitResp =
        call(HttpMethod.Post, "/v1/session/$id/commit", enc(CommitReq.serializer(), req), CommitResp.serializer())
    suspend fun transcript(id: String, req: TranscriptReq): TranscriptResp =
        call(HttpMethod.Post, "/v1/session/$id/transcript", enc(TranscriptReq.serializer(), req), TranscriptResp.serializer())
    suspend fun fail(id: String, attempt: Int, reason: String): SessionView =
        call(HttpMethod.Post, "/v1/session/$id/fail", enc(FailReq.serializer(), FailReq(attempt, reason)), SessionView.serializer())
    suspend fun abort(id: String): SessionView = call(HttpMethod.Post, "/v1/session/$id/abort", "{}", SessionView.serializer())
    /** One request per role serves both buttons (§6.7); the server reuses a live one under 240 s. */
    suspend fun worldidStart(id: String): WorldIdStartResp =
        call(HttpMethod.Post, "/v1/session/$id/worldid/start", "{}", WorldIdStartResp.serializer())

    /** Long-poll (server holds up to 25 s). */
    suspend fun worldidStatus(id: String, timeoutS: Int? = null): WorldIdStatusResp =
        call(HttpMethod.Get, "/v1/session/$id/worldid" + (timeoutS?.let { "?timeout_s=$it" } ?: ""), null, WorldIdStatusResp.serializer())

    /** Public attestation (docs/worldid/01 §8.4), unsigned. */
    suspend fun attestation(id: String): JsonObject =
        call(HttpMethod.Get, "/v1/session/$id/attestation", null, JsonObject.serializer(), signed = false)

    suspend fun result(id: String): ResultRecord = call(HttpMethod.Get, "/v1/session/$id/result", null, ResultRecord.serializer())

    /**
     * Unsigned streaming GET of a static file from byte [from] (Range). [onStart] gets the status and the
     * full size (from Content-Range / Content-Length) before any byte; [onChunk] then gets the body.
     * Returns the status; the body of a non-2xx is not streamed.
     */
    suspend fun download(
        path: String,
        from: Long,
        onStart: suspend (status: Int, total: Long?) -> Unit,
        onChunk: suspend (ByteArray) -> Unit,
    ): Int = client.prepareRequest(base + path) {
        method = HttpMethod.Get
        if (from > 0) header(HttpHeaders.Range, "bytes=$from-")
        timeout { requestTimeoutMillis = 15 * 60_000L; socketTimeoutMillis = 60_000L }
    }.execute { resp ->
        val st = resp.status.value
        val total = resp.headers[HttpHeaders.ContentRange]?.substringAfter('/')?.toLongOrNull()
            ?: resp.headers[HttpHeaders.ContentLength]?.toLongOrNull()?.let { if (st == 206) it + from else it }
        onStart(st, total)
        if (st == 200 || st == 206) {
            val ch = resp.bodyAsChannel()
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = ch.readAvailable(buf, 0, buf.size)
                if (n < 0) break
                if (n > 0) onChunk(buf.copyOf(n))
            }
        }
        st
    }

    /**
     * POST /v1/session/{id}/proof (server/pop/main.py): multipart, file part "proof" = raw proof bytes,
     * "meta" = {"attempt","circuit","salt" (decimal)}. Returns body text.
     */
    suspend fun uploadProof(id: String, attempt: Int, circuit: String, saltDecimal: String, proof: ByteArray): String {
        val boundary = "popzk" + sha256(proof).toHex().take(24)
        val meta = buildJsonObject { put("attempt", attempt); put("circuit", circuit); put("salt", saltDecimal) }
        val body = Multipart.formData(boundary, listOf(
            Multipart.Part("proof", "proof_$attempt.bin", "application/octet-stream", proof),
            Multipart.Part("meta", null, null, meta.toString().encodeToByteArray()),
        ))
        return signedRaw(HttpMethod.Post, "/v1/session/$id/proof", body, ContentType.MultiPart.FormData.withParameter("boundary", boundary))
    }

    /** Raw signed request (e.g. multipart recording upload). Returns body text. */
    suspend fun signedRaw(method: HttpMethod, path: String, body: ByteArray, contentType: ContentType): String =
        send(method, path, body, contentType, signed = true).textOrThrow()

    fun close() = client.close()

    // ---- plumbing ----

    private fun <T> enc(s: KSerializer<T>, v: T) = popJson.encodeToString(s, v)

    private suspend fun <T> call(method: HttpMethod, path: String, body: String?, out: KSerializer<T>, signed: Boolean = true): T {
        val bytes = body?.encodeToByteArray() ?: ByteArray(0)
        val text = send(method, path, bytes, if (body != null) ContentType.Application.Json else null, signed).textOrThrow()
        return popJson.decodeFromString(out, text)
    }

    private suspend fun send(method: HttpMethod, path: String, body: ByteArray, ct: ContentType?, signed: Boolean): HttpResponse {
        if (!signed) return request(method, base + path, body, ct, null)
        val first = request(method, base + path, body, ct, offset())
        if (!clockSync || first.status.value != 401 || errorCode(first.bodyAsText()) != "auth_stale") return first
        clockLock.withLock { syncClock() }
        val again = request(method, base + path, body, ct, offset())
        if (again.status.value == 401) {
            val text = again.bodyAsText()
            val code = errorCode(text)
            if (code == "auth_stale") throw PopHttpException(401, code, text, CLOCK_OFF_TEXT)
        }
        return again
    }

    /** [offsetMs] null = unsigned. */
    private suspend fun request(method: HttpMethod, url: String, body: ByteArray, ct: ContentType?, offsetMs: Long?): HttpResponse {
        val auth = if (offsetMs != null) {
            val k = key() ?: error("not enrolled")
            val u = Url(url)
            val pq = u.encodedPath + (if (u.encodedQuery.isNotEmpty()) "?" + u.encodedQuery else "")
            signRequest(k, method.value, pq, body, nowMs() + offsetMs)
        } else null
        return client.request(url) {
            this.method = method
            if (auth != null) headers {
                append("X-Pop-Device", auth.device)
                append("X-Pop-Ts", auth.ts)
                append("X-Pop-Sig", auth.sig)
            }
            if (ct != null) setBody(ByteArrayContent(body, ct))
        }
    }

    private fun errorCode(text: String): String? =
        runCatching { popJson.parseToJsonElement(text).jsonObject["error"]?.jsonPrimitive?.content }.getOrNull()

    private suspend fun HttpResponse.textOrThrow(): String {
        val text = bodyAsText()
        if (!status.isSuccess()) {
            val code = errorCode(text)
            throw PopHttpException(status.value, code, text)
        }
        return text
    }
}
