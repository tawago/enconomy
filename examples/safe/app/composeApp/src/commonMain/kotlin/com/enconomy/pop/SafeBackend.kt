package com.enconomy.pop

import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpMethod
import io.ktor.http.content.TextContent
import io.ktor.http.isSuccess
import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** POST /v1/spends answer. [what] is the backend's reading: the app shows its own, from Allowlist. */
@Serializable data class SpendCreated(val ctx_hash: String, val what: JsonObject? = null)

/** GET /v1/spends/{ctx_hash}. */
@Serializable
data class SpendRow(val ctx_hash: String, val chain_id: Long, val safe: String, val safe_tx: JsonObject, val what: JsonObject? = null)

/** POST /v1/spends/{ctx_hash}/presence answer. [relay] = status of the send. */
@Serializable
data class PresenceResp(val session_id: String, val ctx_hash: String, val att: JsonObject? = null, val relay: String? = null)

/** GET /v1/spends/{ctx_hash}/relay. [result] = the line relay.mjs printed: tx_hash, link, text, error. */
@Serializable data class RelayResp(val status: String, val session_id: String? = null, val result: JsonObject? = null)

/**
 * The Safe backend (examples/safe/README.md, API). Its own URL, no device signature, no /v1/time:
 * so this isn't a PopApi. Errors are {error, detail} as in the core, so they throw [PopHttpException] too.
 */
class SafeBackend(baseUrl: String, engine: HttpClientEngine? = null) {
    val base = baseUrl.trim().trimEnd('/')

    private val cfg: HttpClientConfig<*>.() -> Unit = {
        install(HttpTimeout) {
            requestTimeoutMillis = 40_000
            connectTimeoutMillis = 10_000
        }
        expectSuccess = false
    }
    private val client = if (engine != null) HttpClient(engine, cfg) else HttpClient(cfg)

    suspend fun createSpend(chainId: Long, safe: String, safeTx: JsonObject): SpendCreated {
        val body = buildJsonObject { put("chain_id", chainId); put("safe", safe); put("safe_tx", safeTx) }
        return call(HttpMethod.Post, "/v1/spends", body.toString(), SpendCreated.serializer())
    }

    suspend fun spend(ctxHash: String): SpendRow = call(HttpMethod.Get, "/v1/spends/$ctxHash", null, SpendRow.serializer())

    /** [pubkeyHex] 65-byte SEC1 hex, [sigHex] lowercase 0x + r||s over [com.enconomy.pop.chain.SafeTx.ownerMessage]. */
    suspend fun ownerSig(ctxHash: String, pubkeyHex: String, sigHex: String) {
        val body = buildJsonObject { put("pubkey", pubkeyHex); put("sig", sigHex) }
        call(HttpMethod.Post, "/v1/spends/$ctxHash/owner-sig", body.toString(), JsonObject.serializer())
    }

    /** [presence] = the core's {body, sig_b64}, sent as it came: the core's signature covers the body. */
    suspend fun presence(ctxHash: String, presence: JsonObject): PresenceResp =
        call(HttpMethod.Post, "/v1/spends/$ctxHash/presence", presence.toString(), PresenceResp.serializer())

    suspend fun relay(ctxHash: String): RelayResp = call(HttpMethod.Get, "/v1/spends/$ctxHash/relay", null, RelayResp.serializer())

    fun close() = client.close()

    private suspend fun <T> call(method: HttpMethod, path: String, body: String?, out: KSerializer<T>): T {
        val resp = client.request(base + path) {
            this.method = method
            if (body != null) setBody(TextContent(body, ContentType.Application.Json))
        }
        val text = resp.bodyAsText()
        if (!resp.status.isSuccess()) {
            val code = runCatching { popJson.parseToJsonElement(text).jsonObject["error"]?.jsonPrimitive?.content }.getOrNull()
            throw PopHttpException(resp.status.value, code, text)
        }
        return popJson.decodeFromString(out, text)
    }
}
