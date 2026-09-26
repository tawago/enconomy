package com.enconomy.pop.chain

import com.enconomy.pop.hexToBytes
import com.enconomy.pop.toHex
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put

/**
 * Safe (>= 1.3, here 1.5.0 SafeL2 on Ethereum Sepolia) EIP-712 SafeTx, same as server pop/consumers/safe_tx.py.
 * Wire form = the server's context.safe_tx: addresses lowercase 0x+40 hex, uint256 fields canonical decimal
 * strings, data lowercase 0x hex, operation a JSON int.
 */
data class SafeTx(
    val to: String,
    val value: String = "0",
    val data: String = "0x",
    val operation: Int = 0,
    val safeTxGas: String = "0",
    val baseGas: String = "0",
    val gasPrice: String = "0",
    val gasToken: String = ZERO,
    val refundReceiver: String = ZERO,
    val nonce: String = "0",
) {
    fun json(): JsonObject = buildJsonObject {
        put("to", to); put("value", value); put("data", data); put("operation", operation)
        put("safe_tx_gas", safeTxGas); put("base_gas", baseGas); put("gas_price", gasPrice)
        put("gas_token", gasToken); put("refund_receiver", refundReceiver); put("nonce", nonce)
    }

    companion object {
        const val KIND = "safe-tx"
        const val CHAIN_SEPOLIA = 11155111L
        const val ZERO = "0x0000000000000000000000000000000000000000"
        val OWNER_MSG_TAG = "pop-safe-owner-v1".encodeToByteArray()
        private val SAFE_TX_TYPEHASH = "bb8310d486368db6bd6f849402fdd73ad53d316b5a4b2644ad6efe0f941286d8".hexToBytes()
        private val DOMAIN_TYPEHASH = "47e79534a245952e8b16893a336b85a3d9ea9fa8c573f3d803afb92a79469218".hexToBytes()
        private val ADDR = Regex("^0x[0-9a-f]{40}$")
        private val DEC = Regex("^(0|[1-9][0-9]{0,77})$")
        private val DATA = Regex("^0x([0-9a-f]{2})*$")

        fun fromJson(o: JsonObject): SafeTx? {
            fun s(k: String) = (o[k] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val op = (o["operation"] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull ?: return null
            val t = SafeTx(
                to = s("to") ?: return null, value = s("value") ?: return null, data = s("data") ?: return null,
                operation = op, safeTxGas = s("safe_tx_gas") ?: return null, baseGas = s("base_gas") ?: return null,
                gasPrice = s("gas_price") ?: return null, gasToken = s("gas_token") ?: return null,
                refundReceiver = s("refund_receiver") ?: return null, nonce = s("nonce") ?: return null,
            )
            return t.takeIf { it.valid() }
        }

        /** keccak(0x1901 ‖ domainSeparator(chainId, safe) ‖ structHash(tx)). */
        fun hash(chainId: Long, safe: String, t: SafeTx): ByteArray {
            require(t.valid()) { "bad safe tx" }
            require(ADDR.matches(safe)) { "bad safe address" }
            val k = PopCtx::keccak
            val ds = k(DOMAIN_TYPEHASH + u256(chainId.toString()) + addr(safe))
            val sh = k(SAFE_TX_TYPEHASH + addr(t.to) + u256(t.value) + k(t.data.drop(2).hexToBytes()) +
                u256(t.operation.toString()) + u256(t.safeTxGas) + u256(t.baseGas) + u256(t.gasPrice) +
                addr(t.gasToken) + addr(t.refundReceiver) + u256(t.nonce))
            return k(byteArrayOf(0x19, 0x01) + ds + sh)
        }

        fun hashHex(chainId: Long, safe: String, t: SafeTx): String = "0x" + hash(chainId, safe, t).toHex()

        /** The session context the server's safe_tx consumer takes (contracts/README.md "Run the demo" 4). */
        fun context(chainId: Long, safe: String, t: SafeTx): JsonObject = buildJsonObject {
            put("kind", KIND); put("chain_id", chainId); put("consumer", safe)
            put("ctx_hash", hashHex(chainId, safe, t)); put("safe_tx", t.json())
        }

        /** Guest side of the context gate: the ctx_hash this phone derives from context.safe_tx, null = can't. */
        fun expectCtxHash(context: JsonObject): String? {
            val chain = (context["chain_id"] as? JsonPrimitive)?.content?.toLongOrNull() ?: return null
            val safe = (context["consumer"] as? JsonPrimitive)?.content ?: return null
            val t = (context["safe_tx"] as? JsonObject)?.let(::fromJson) ?: return null
            return runCatching { hashHex(chain, safe, t) }.getOrNull()
        }

        /** What each phone signs at Confirm (P256Owner, SHA256withECDSA): "pop-safe-owner-v1" ‖ safeTxHash. */
        fun ownerMessage(safeTxHash: ByteArray): ByteArray {
            require(safeTxHash.size == 32)
            return OWNER_MSG_TAG + safeTxHash
        }

        /** "0.0015" ETH -> wei decimal string; null = not a non-negative decimal with <= 18 places. */
        fun ethToWei(eth: String): String? {
            val s = eth.trim()
            if (!Regex("^[0-9]+(\\.[0-9]{0,18})?$").matches(s) && !Regex("^\\.[0-9]{1,18}$").matches(s)) return null
            val (i, f) = s.split('.').let { it[0] to (it.getOrNull(1) ?: "") }
            return (i + f.padEnd(18, '0')).trimStart('0').ifEmpty { "0" }
        }

        fun addrOk(a: String) = ADDR.matches(a)

        internal fun addr(a: String): ByteArray = ByteArray(12) + a.drop(2).hexToBytes()

        /** Canonical decimal -> 32-byte big-endian. */
        internal fun u256(dec: String): ByteArray {
            require(DEC.matches(dec)) { "bad uint $dec" }
            val out = ByteArray(32)
            for (ch in dec) {
                var carry = ch - '0'
                for (i in 31 downTo 0) {
                    val v = (out[i].toInt() and 0xff) * 10 + carry
                    out[i] = v.toByte()
                    carry = v ushr 8
                }
                require(carry == 0) { "uint256 overflow" }
            }
            return out
        }

        /** 0x-hex quantity (JSON-RPC) -> decimal string. */
        fun hexToDec(h: String): String {
            val b = h.removePrefix("0x").let { if (it.length % 2 == 1) "0$it" else it }.hexToBytes()
            val digits = mutableListOf(0)
            for (byte in b) {
                var carry = byte.toInt() and 0xff
                for (i in digits.indices) {
                    val v = digits[i] * 256 + carry
                    digits[i] = v % 10
                    carry = v / 10
                }
                while (carry > 0) { digits.add(carry % 10); carry /= 10 }
            }
            return digits.reversed().joinToString("").trimStart('0').ifEmpty { "0" }
        }
    }

    fun valid(): Boolean = ADDR.matches(to) && ADDR.matches(gasToken) && ADDR.matches(refundReceiver) &&
        DATA.matches(data) && operation in 0..1 &&
        listOf(value, safeTxGas, baseGas, gasPrice, nonce).all { DEC.matches(it) }
}
