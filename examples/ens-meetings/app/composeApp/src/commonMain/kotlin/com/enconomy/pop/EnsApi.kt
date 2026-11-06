package com.enconomy.pop

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

// This example's own backend (examples/ens-meetings/backend), not the core. See the example README, "API".

val ENS_LABEL = Regex("^[a-z0-9-]{3,32}$")
const val ENS_SUFFIX = ".enconomy.eth"

/** Prefs key of the core's device statement, JSON. */
const val ENS_STATEMENT_PREF = "ens.statement"

/** How long a phone waits for the pair proof before it stops watching. A phone proof takes minutes, the key download more. */
const val PAIR_PROOF_WATCH_MS = 15 * 60_000L

/** Build-time ENS backend URL (-Ppop.ensUrl / POP_ENS_URL). A saved Prefs value wins. */
val DEFAULT_ENS_URL: String = PopBuildConfig.ENS_URL

/** status none | pending | registered | failed. */
@Serializable data class EnsResp(val label: String? = null, val name: String? = null, val status: String = "none", val tx: String? = null)

@Serializable data class PresenceResp(val session_id: String, val status: String)

/**
 * What the device key signs: "ens-claim-v1\n" + canonical({device_id, label, ts}), label null for a read.
 * Keys sorted, no spaces. Device id is hex and a claim's label is [ENS_LABEL], so nothing here needs escaping.
 */
fun ensClaimMessage(deviceId: String, label: String?, ts: Long): ByteArray {
    val l = if (label == null) "null" else "\"$label\""
    return ("ens-claim-v1\n{\"device_id\":\"$deviceId\",\"label\":$l,\"ts\":$ts}").encodeToByteArray()
}

class EnsApi(baseUrl: String) {
    private val http = PopApi(baseUrl, clockSync = false)

    suspend fun claim(statement: JsonObject, label: String, ts: Long, sig: String): EnsResp {
        val body = buildJsonObject {
            put("device_statement", statement)
            put("label", label)
            put("ts", ts)
            put("sig_b64", sig)
        }
        return popJson.decodeFromString(EnsResp.serializer(), http.postJson("/v1/names/claim", body.toString()))
    }

    suspend fun read(statement: JsonObject, ts: Long, sig: String): EnsResp {
        val body = buildJsonObject {
            put("device_statement", statement)
            put("ts", ts)
            put("sig_b64", sig)
        }
        return popJson.decodeFromString(EnsResp.serializer(), http.postJson("/v1/names/read", body.toString()))
    }

    /** [record] = `presence` from the core's result, {body, sig_b64}, as it came. */
    suspend fun presence(record: JsonObject): PresenceResp =
        popJson.decodeFromString(PresenceResp.serializer(), http.postJson("/v1/presence", record.toString()))

    fun close() = http.close()
}
