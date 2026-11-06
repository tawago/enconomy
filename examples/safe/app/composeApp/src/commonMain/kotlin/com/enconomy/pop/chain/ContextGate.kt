package com.enconomy.pop.chain

import com.enconomy.pop.toHex
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * The gate both phones run before Confirm and before any signature:
 *  1. the context's Safe is the one saved on this phone, else unknown_consumer
 *  2. chain and Safe agree across the session and the spend, and safe_tx recomputes ctx_hash, else context_mismatch
 *  3. this phone's own allowlist takes the transaction, else context_refused
 * Once both confirmed the core shows the nonce: [nonceOk] recomputes it before the run.
 */
object ContextGate {
    const val UNKNOWN_CONSUMER = "unknown_consumer"
    const val CONTEXT_MISMATCH = "context_mismatch"
    const val CONTEXT_REFUSED = "context_refused"
    const val SPEND_UNAVAILABLE = "spend_unavailable"

    private val KEYS = setOf("chain_id", "consumer", "ctx_hash")
    private val HEX40 = Regex("^0x[0-9a-f]{40}$")
    private val HEX64 = Regex("^0x[0-9a-f]{64}$")

    data class Spend(val chainId: Long, val safe: String, val ctxHash: String, val tx: SafeTx, val what: Allowlist.What)

    sealed class Result {
        data class Ok(val spend: Spend) : Result()
        data class Refused(val code: String, val why: String) : Result()
    }

    fun text(r: Result.Refused): String = when (r.code) {
        UNKNOWN_CONSUMER -> "This request is for a Safe that isn't saved on this phone. Not approving."
        CONTEXT_REFUSED -> "This phone won't sign this transaction (${r.why}). Not approving."
        SPEND_UNAVAILABLE -> "Couldn't get the transaction from the Safe backend (${r.why}). Not approving."
        else -> "This request doesn't match (${r.why}). Not approving."
    }

    /** The context's ctx_hash when it has the right form, so it's safe to put in a URL. */
    fun ctxHash(context: JsonObject): String? =
        (context["ctx_hash"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.takeIf { HEX64.matches(it) }

    /**
     * @param context the session's plain context
     * @param safeTx the spend's safe_tx: this phone's own on the host, from GET /v1/spends/{ctx_hash} on the guest
     * @param spendChain, spendSafe the spend's chain_id and safe
     * @param mySafe the Safe saved on this phone
     * @param coreChain the core's chain_id
     */
    fun check(context: JsonObject, safeTx: JsonObject, spendChain: Long, spendSafe: String, mySafe: String?, coreChain: Long): Result {
        fun mismatch(why: String) = Result.Refused(CONTEXT_MISMATCH, why)
        if (context.keys != KEYS) return mismatch("context keys")
        val chainId = (context["chain_id"] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull ?: return mismatch("chain_id")
        val safe = (context["consumer"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.takeIf { HEX40.matches(it) } ?: return mismatch("consumer")
        val ctxHash = ctxHash(context) ?: return mismatch("ctx_hash")
        if (safe != mySafe) return Result.Refused(UNKNOWN_CONSUMER, safe)
        if (chainId != coreChain || chainId != spendChain) return mismatch("chain_id")
        if (safe != spendSafe) return mismatch("safe")
        val tx = SafeTx.fromJson(safeTx) ?: return mismatch("safe_tx")
        val want = runCatching { SafeTx.hashHex(chainId, safe, tx) }.getOrNull() ?: return mismatch("safe_tx")
        if (want != ctxHash) return mismatch("ctx_hash")
        return when (val a = Allowlist.check(chainId, safe, tx)) {
            is Allowlist.Result.Refused -> Result.Refused(CONTEXT_REFUSED, a.reason)
            is Allowlist.Result.Ok -> Result.Ok(Spend(chainId, safe, ctxHash, tx, a.what))
        }
    }

    fun nonceOk(spend: Spend, sessionId: String, notBefore: Long?, nonce: String?): Boolean {
        val nb = notBefore ?: return false
        val got = nonce?.lowercase()?.removePrefix("0x") ?: return false
        return runCatching { PopCtx.nonce(spend.chainId, spend.safe, spend.ctxHash, nb, sessionId).toHex() }.getOrNull() == got
    }
}
