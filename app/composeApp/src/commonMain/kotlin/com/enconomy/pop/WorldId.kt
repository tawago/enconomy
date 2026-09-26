package com.enconomy.pop

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * World ID hop (docs/worldid/01 §6, §7.2, §12): statuses, per-role view parsing and the §6.9 screen texts.
 * Server states: idle, requested, waiting, awaiting, verifying, verified, failed.
 */
object WorldId {
    const val VERIFIED = "verified"
    const val FAILED = "failed"

    /** Deep link World App returns to (server POP_WORLDID_RETURN_TO). */
    const val RETURN_SCHEME = "enconomy"
    const val RETURN_HOST = "worldid"

    fun isReturnLink(url: String?): Boolean =
        url != null && url.lowercase().startsWith("$RETURN_SCHEME://$RETURN_HOST")

    /** policy.human == "worldid" in a view or create response. */
    fun required(policy: JsonObject?): Boolean = policy.str("human") == "worldid"

    data class Role(val status: String, val error: String? = null, val env: String? = null) {
        val sandbox: Boolean get() = env == "sandbox"
    }

    /** view.human = {A:{status, error?}, B:{...}, pair_tag}. Missing = idle. */
    fun role(human: JsonObject?, role: String): Role {
        val o = human?.get(role) as? JsonObject ?: return Role("idle")
        return Role(o.str("status") ?: "idle", o.str("error"), o.str("env"))
    }

    fun pairTag(human: JsonObject?): String? = human.str("pair_tag")

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

    /** §6.9 error code (server or IDKit) -> screen text. */
    fun errorText(code: String?): String {
        val c = code?.lowercase().orEmpty()
        return when {
            c == "human_missing" -> "Waiting for the other person's World ID"
            c == "human_level" -> "This needs an Orb-verified World ID"
            c == "same_human" -> "Both phones used the same World ID. Two different people are needed."
            "nullifier_replayed" in c -> "Both phones used the same World ID. Two different people are needed. Start a new session."
            c == "human_expired" || "expired" in c -> "World ID request expired. Tap to retry."
            c == "worldid_unavailable" -> "World ID is unreachable"
            "user_rejected" in c || "cancel" in c -> "Cancelled in World ID. Confirm stays off."
            c == "not_joined" -> "Waiting for the partner to join"
            c == "sandbox_not_allowed" -> "This server or session does not allow sandbox World ID. Turn it off in Tools."
            c == "network" -> "No connection to the server. Retrying…"
            else -> "World ID check failed. Try again."
        }
    }

    /** Only a new session (new action) can fix these; everything else can retry in this session. */
    fun needsNewSession(code: String?): Boolean {
        val c = code?.lowercase().orEmpty()
        return c == "same_human" || "nullifier_replayed" in c
    }

    private fun JsonObject?.str(k: String): String? =
        (this?.get(k) as? JsonPrimitive)?.takeIf { it.isString }?.content
}

/** This phone's World ID step. [connectorUri] serves both buttons (§6.7); null until /worldid/start answered. */
data class WidUi(
    val status: String = "idle",
    val error: String? = null,
    val connectorUri: String? = null,
    val expiresAtS: Long? = null,
    /** "app" = open World ID on this phone, "qr" = show the code to another phone. */
    val mode: String = "app",
    /** This role's request is a World ID Simulator (sandbox) request. */
    val sandbox: Boolean = false,
) {
    val verified: Boolean get() = status == WorldId.VERIFIED
    val failed: Boolean get() = status == WorldId.FAILED
}
