package com.enconomy.pop.chain

/**
 * The backend's allowlist (examples/safe/backend/safe_tx.py), run again on each phone before Confirm.
 * Same checks, same order, same reasons. Takes a [SafeTx] that passed [SafeTx.valid].
 * The token table lives here on purpose: the phone doesn't take the backend's word for what a token is.
 */
object Allowlist {
    data class Token(val address: String, val symbol: String, val decimals: Int)

    /** ERC-20s the allowlist accepts, per chain. Keep equal to TOKENS in safe_tx.py. */
    val TOKENS: Map<Long, List<Token>> = mapOf(
        480L to listOf(
            Token("0x2cfc85d8e48f8eab294be644d9e25c3030863003", "WLD", 18),   // spec vectors (World Chain)
            Token("0x79a02482a880bce3f13e09da970dc34db4cd24d1", "USDC", 6),
        ),
        11155111L to listOf(Token("0x1c7d4b196cb0c7b01d743fbc6116a902379c7238", "USDC", 6)),  // Circle USDC, Ethereum Sepolia
    )

    fun token(chainId: Long, address: String): Token? = TOKENS[chainId]?.firstOrNull { it.address == address }

    /** What the transaction actually does. */
    sealed class What {
        data class Native(val to: String, val wei: String) : What()
        data class Erc20(val token: Token, val to: String, val amount: String) : What()
    }

    sealed class Result {
        data class Ok(val what: What) : Result()
        data class Refused(val reason: String) : Result()
    }

    fun check(chainId: Long, safe: String, t: SafeTx): Result {
        if (t.operation != 0) return Result.Refused("delegatecall")
        if (t.safeTxGas != "0" || t.baseGas != "0" || t.gasPrice != "0" || t.gasToken != SafeTx.ZERO || t.refundReceiver != SafeTx.ZERO)
            return Result.Refused("gas_refund_fields")
        if (t.to == safe) return Result.Refused("self_call")
        val hasValue = t.value != "0"
        val hasData = t.data != "0x"
        if (hasValue && hasData) return Result.Refused("value_with_call")
        if (!hasData && hasValue) return Result.Ok(What.Native(t.to, t.value))
        val tok = token(chainId, t.to)
        // data, hex without 0x: selector 8, zero padding 24, recipient 40, amount 64
        val d = t.data.drop(2)
        if (tok != null && !hasValue && d.length == 136 && d.startsWith(SafeTx.TRANSFER) && d.substring(8, 32).all { it == '0' }) {
            val amount = SafeTx.hexToDec(d.substring(72))
            if (amount != "0") return Result.Ok(What.Erc20(tok, "0x" + d.substring(32, 72), amount))
        }
        return Result.Refused("unknown_call")
    }
}
