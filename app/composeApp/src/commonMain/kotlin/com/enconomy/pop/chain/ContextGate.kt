package com.enconomy.pop.chain

import com.enconomy.pop.toHex
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * Context gate (docs/worldid/01 §7.1, §12), both roles, before World ID / Confirm / any signature:
 *  1. consumer is one we know (02 "My Safes", 03 scanned popctx1; kind "test": any, debug builds only) else unknown_consumer
 *  2. the kind recomputes ctx_hash (kind "test": accepted as-is) else context_mismatch
 *  3. PopCtx.nonce(chain_id, consumer, ctx_hash, not_before, sid) == view nonce else context_mismatch
 * A session without a context passes (policy none, the v1/v2 flows).
 */
object ContextGate {
    const val UNKNOWN_CONSUMER = "unknown_consumer"
    const val CONTEXT_MISMATCH = "context_mismatch"

    /** §6.9 screen text. */
    fun text(code: String): String = when (code) {
        UNKNOWN_CONSUMER -> "Unknown account in this request. Not approving."
        else -> "This request doesn't match. Not approving."
    }

    sealed class Result {
        /** No context: nothing to bind. */
        data object NoContext : Result()
        data class Ok(val nonceHex: String, val kind: String, val consumer: String, val ctxHash: String) : Result()
        data class Refused(val code: String, val why: String) : Result()
    }

    /**
     * @param expectCtxHash per-kind recompute: returns the ctx_hash the phone derives from the context's kind
     *   fields, or null when this phone can't (unknown kind -> refused). Kind "test" needs none.
     */
    fun check(
        sessionId: String,
        context: JsonObject?,
        notBefore: Long?,
        nonce: String?,
        knownConsumers: Set<String> = emptySet(),
        allowTestKind: Boolean = false,
        expectCtxHash: (kind: String, context: JsonObject) -> String? = { _, _ -> null },
    ): Result {
        if (context == null) return Result.NoContext
        fun mismatch(why: String) = Result.Refused(CONTEXT_MISMATCH, why)
        val kind = context.str("kind") ?: return mismatch("no kind")
        val chainId = (context["chain_id"] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull ?: return mismatch("bad chain_id")
        val consumer = context.str("consumer")?.takeIf { HEX40.matches(it) } ?: return mismatch("bad consumer")
        val ctxHash = context.str("ctx_hash")?.takeIf { HEX64.matches(it) } ?: return mismatch("bad ctx_hash")
        val nb = notBefore ?: return mismatch("no not_before")
        val got = nonce?.lowercase()?.removePrefix("0x") ?: return mismatch("no nonce")

        val isTest = kind == "test"
        if (isTest && !allowTestKind) return Result.Refused(UNKNOWN_CONSUMER, "test kind off in this build")
        if (!isTest && consumer !in knownConsumers.map { it.lowercase() }) return Result.Refused(UNKNOWN_CONSUMER, "consumer $consumer")
        if (!isTest) {
            val want = expectCtxHash(kind, context) ?: return mismatch("can't recompute kind $kind")
            if (want.lowercase() != ctxHash) return mismatch("ctx_hash")
        }
        val mine = try {
            PopCtx.nonce(chainId, consumer, ctxHash, nb, sessionId).toHex()
        } catch (e: IllegalArgumentException) {
            return mismatch(e.message ?: "bad input")
        }
        if (mine != got) return mismatch("nonce")
        return Result.Ok("0x$mine", kind, consumer, ctxHash)
    }

    private fun JsonObject.str(k: String): String? = (this[k] as? JsonPrimitive)?.takeIf { it.isString }?.content

    // §9 row 1: consumer lowercase 0x+40 hex, ctx_hash lowercase 0x+64 hex.
    private val HEX40 = Regex("^0x[0-9a-f]{40}$")
    private val HEX64 = Regex("^0x[0-9a-f]{64}$")
}
