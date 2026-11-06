package com.enconomy.pop

import io.ktor.client.HttpClient
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * World ID step, run through this example's backend (examples/world-id/backend), not the core.
 * Backend states: idle, requested, waiting, awaiting, verifying, verified, failed.
 */
object WorldId {
    const val VERIFIED = "verified"
    const val FAILED = "failed"

    /** Deep link World App returns to. The backend's WID_RETURN_TO must say the same. */
    const val RETURN_SCHEME = "enconomy"
    const val RETURN_HOST = "worldid"

    fun isReturnLink(url: String?): Boolean =
        url != null && url.lowercase().startsWith("$RETURN_SCHEME://$RETURN_HOST")

    fun statusText(status: String): String = when (status) {
        "idle" -> "Not started"
        "starting" -> "Preparing World ID…"
        "requested" -> "Open World ID to continue"
        "waiting" -> "Waiting for the World ID app"
        "awaiting" -> "Approve in the World ID app"
        "verifying" -> "Checking the proof…"
        VERIFIED -> "Verified human"
        FAILED -> "Failed"
        else -> status
    }

    /** Backend or IDKit error code -> screen text. */
    fun errorText(code: String?): String {
        val c = code?.lowercase().orEmpty()
        return when {
            c == "human_level" -> "This needs an Orb-verified World ID"
            c == "same_human" -> "Both phones used the same World ID. Two different people are needed."
            c == "nullifier_used" -> "This World ID was already used for this session. Start a new session."
            c == "human_expired" || "expired" in c -> "World ID request expired. Tap to retry."
            c == "worldid_unavailable" -> "World ID is unreachable"
            "user_rejected" in c || "cancel" in c -> "Cancelled in World ID. Confirm stays off."
            c == "network" -> "No connection to the World ID backend. Retrying…"
            else -> "World ID check failed. Try again."
        }
    }

    /** Only a new session (new action) can fix these; everything else can retry in this session. */
    fun needsNewSession(code: String?): Boolean {
        val c = code?.lowercase().orEmpty()
        return c == "same_human" || c == "nullifier_used"
    }

    /** POST /v1/record `reason` -> screen text. */
    fun reasonText(reason: String?): String = when (reason) {
        "not_near" -> "The phones were not near each other."
        "no_world_id" -> "The backend has no World ID from both phones for this session."
        "session_id_mismatch" -> "The World IDs were given for another session."
        "role_unverified" -> "One of the two World IDs isn't verified."
        "same_human" -> "Both phones used the same World ID."
        "pubkey_mismatch" -> "The World ID came from another device than the one measured."
        else -> reason ?: "The backend said no."
    }
}

/** This phone's World ID step, plus the partner's status from the same backend answer. */
data class WidUi(
    val status: String = "idle",
    val error: String? = null,
    val connectorUri: String? = null,
    val expiresAtS: Long? = null,
    /** "app" = open World ID on this phone, "qr" = show the code to another phone. */
    val mode: String = "app",
    val partnerStatus: String = "idle",
) {
    val verified: Boolean get() = status == WorldId.VERIFIED
    val failed: Boolean get() = status == WorldId.FAILED
    /** Both verified: Confirm, and so Arm, may go ahead. A courtesy, the backend's /v1/record is the real check. */
    val bothVerified: Boolean get() = verified && partnerStatus == WorldId.VERIFIED
}

@Serializable data class WorldIdStartResp(val request_id: String? = null, val connector_uri: String, val expires_at_s: Long? = null, val status: String? = null)
@Serializable data class WorldIdPartner(val status: String = "idle")

@Serializable
data class WorldIdStatusResp(
    val role: String? = null,
    val status: String,
    val error: String? = null,
    val partner: WorldIdPartner = WorldIdPartner(),
    val connector_uri: String? = null,
    val expires_at_s: Long? = null,
)

/** POST /v1/record's answer. */
@Serializable
data class MeetingAnswer(
    val met: Boolean,
    val reason: String? = null,
    val session_id: String? = null,
    val session_nonce: String? = null,
    val finished_at: String? = null,
    val flight_cm: String? = null,
    val trust_tier: JsonObject? = null,
)

const val WID_DEVICE_TAG = "wid-device-v1\n"

/** canonical JSON of the signed fields: sorted keys, no spaces. All values are hex or digits, so nothing needs escaping. */
fun widDeviceCanonical(nonce: String, sessionId: String, role: String, pubkeyHex: String, ts: Long): String =
    """{"pubkey":"$pubkeyHex","role":"$role","session_id":"$sessionId","session_nonce":"$nonce","ts":$ts}"""

/**
 * The example backend. Not [PopApi]: no X-Pop headers and no /v1/time, a device request carries its own key and signature.
 * The key is the one enrolled with the core: the backend compares it against the core's signed record later.
 */
class WorldIdApi(
    baseUrl: String,
    private val key: () -> DeviceKey?,
    private val nowMs: () -> Long = ::unixMs,
    engine: HttpClientEngine? = null,
) {
    val base = baseUrl.trim().trimEnd('/')
    private val client = (engine?.let { HttpClient(it) { config() } } ?: HttpClient { config() })

    private fun io.ktor.client.HttpClientConfig<*>.config() {
        install(HttpTimeout) {
            requestTimeoutMillis = 40_000 // a status call can wait on the Portal
            connectTimeoutMillis = 10_000
        }
        expectSuccess = false
    }

    suspend fun start(nonce: String, sessionId: String, role: String): WorldIdStartResp =
        post("/v1/worldid/start", deviceRequest(nonce, sessionId, role), WorldIdStartResp.serializer())

    suspend fun status(nonce: String, sessionId: String, role: String): WorldIdStatusResp =
        post("/v1/worldid/status", deviceRequest(nonce, sessionId, role), WorldIdStatusResp.serializer())

    /** [presence] = the core's {body, sig_b64} as it came, unsigned here: the core's signature is the auth. */
    suspend fun record(presence: JsonObject): MeetingAnswer =
        post("/v1/record", presence.toString(), MeetingAnswer.serializer())

    fun close() = client.close()

    /** {session_nonce, session_id, role, pubkey, ts, sig_b64}, signed over the tag + canonical of the other five. */
    private suspend fun deviceRequest(nonce: String, sessionId: String, role: String): String {
        val k = key() ?: error("not enrolled")
        val pk = k.pubkey.toHex()
        val ts = nowMs()
        val canon = widDeviceCanonical(nonce, sessionId, role, pk, ts)
        val sig = withContext(Dispatchers.Default) { k.sign((WID_DEVICE_TAG + canon).encodeToByteArray()) }
        return canon.dropLast(1) + ""","sig_b64":"${sig.toB64()}"}"""
    }

    private suspend fun <T> post(path: String, body: String, out: KSerializer<T>): T {
        val r = client.post(base + path) {
            contentType(ContentType.Application.Json)
            setBody(body)
        }
        val text = r.bodyAsText()
        if (!r.status.isSuccess()) {
            val code = runCatching { popJson.parseToJsonElement(text).jsonObject["error"]?.jsonPrimitive?.content }.getOrNull()
            throw PopHttpException(r.status.value, code, text)
        }
        return popJson.decodeFromString(out, text)
    }
}
