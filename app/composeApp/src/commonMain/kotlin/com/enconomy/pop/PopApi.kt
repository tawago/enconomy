package com.enconomy.pop

import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.HttpTimeout
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
import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
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
)

@Serializable data class EnrollResp(val device_id: String, val attested: Boolean = false, val enrolled_at: JsonElement? = null)

@Serializable
data class CreateSessionResp(val session_id: String, val join_token: String, val expires_at_ms: Long, val invite_b64url: String? = null)

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
)

@Serializable data class Pcm(val pcm_b64: String, val n: Int)
@Serializable data class ArmReq(val attempt: Int, val sample_rate: Int, val rtt_min_ms: Double)
@Serializable data class ArmResp(val attempt: Int, val sample_rate: Int, val play: Pcm, val own_bed: Pcm)
@Serializable data class CommitReq(val commit_b64: String, val sig_b64: String)
@Serializable data class CommitResp(val partner_bed: Pcm)
@Serializable data class TranscriptReq(val transcript_b64: String, val sig_b64: String, val meta: JsonObject)
@Serializable data class TranscriptResp(val accepted: Boolean, val state: String? = null)
@Serializable data class FailReq(val attempt: Int, val reason: String)
@Serializable class Empty

/** Non-2xx. [code] = `error` field of the body when present. */
class PopHttpException(val status: Int, val code: String?, val body: String) :
    Exception("HTTP $status ${code ?: ""}: ${body.take(300)}")

val popJson = Json { ignoreUnknownKeys = true; encodeDefaults = true; explicitNulls = true }

/**
 * Contract API client. [key] signs every call after enroll (§2.3).
 * Signed path = URL encoded path + query as sent (includes any prefix in [baseUrl]).
 */
class PopApi(
    baseUrl: String,
    private val key: () -> DeviceKey? = { null },
    private val nowMs: () -> Long = ::unixMs,
    engine: HttpClientEngine? = null,
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

    // ---- unsigned ----
    suspend fun time(): TimeResp = call(HttpMethod.Get, "/v1/time", null, TimeResp.serializer(), signed = false)
    suspend fun config(): JsonObject = call(HttpMethod.Get, "/v1/config", null, JsonObject.serializer(), signed = false)
    suspend fun enrollNonce(): NonceResp = call(HttpMethod.Get, "/v1/enroll/nonce", null, NonceResp.serializer(), signed = false)
    suspend fun enroll(req: EnrollReq): EnrollResp =
        call(HttpMethod.Post, "/v1/enroll", enc(EnrollReq.serializer(), req), EnrollResp.serializer(), signed = false)

    // ---- signed ----
    suspend fun createSession(): CreateSessionResp =
        call(HttpMethod.Post, "/v1/session", "{}", CreateSessionResp.serializer())

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
    suspend fun result(id: String): JsonObject = call(HttpMethod.Get, "/v1/session/$id/result", null, JsonObject.serializer())

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
        val url = base + path
        val auth = if (signed) {
            val k = key() ?: error("not enrolled")
            val u = Url(url)
            val pq = u.encodedPath + (if (u.encodedQuery.isNotEmpty()) "?" + u.encodedQuery else "")
            signRequest(k, method.value, pq, body, nowMs())
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

    private suspend fun HttpResponse.textOrThrow(): String {
        val text = bodyAsText()
        if (!status.isSuccess()) {
            val code = runCatching { popJson.parseToJsonElement(text).jsonObject["error"]?.jsonPrimitive?.content }.getOrNull()
            throw PopHttpException(status.value, code, text)
        }
        return text
    }
}
