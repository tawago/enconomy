package com.enconomy.pop.chain

import com.enconomy.pop.hexToBytes
import com.enconomy.pop.toHex
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

/** PopCtx golden vectors (checked with pycryptodome, forge, cast) and the gate. */
class PopCtxTest {
    private val safe = "0x" + "5afe".repeat(10)
    private val guard = "0x" + "6a7d".repeat(10)
    private val pool = "0x" + "9001".repeat(10)
    private val ctx = "0x" + ByteArray(32) { (0xa0 + it).toByte() }.toHex()
    private val nb = 1790000000L
    private val sid = "00112233445566778899aabbccddeeff"

    private val gNonce = "2b9a8528bf222c8cf60dd97fb416183376bd4bc5425b29c02583518590ef75c9"
    private val nSafe = "0x3fad7600f309b0c3d60a57023b0262460b0603dc"
    private val nCtx = "0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5"

    @Test fun domain() {
        assertEquals("2c71bde9118937099ebb172d5845794f571cc2982d44a563b229d1ea0db2af2f", PopCtx.DOMAIN.toHex())
        // Keccak-256, not SHA3-256: empty-input vector
        assertEquals("c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470", PopCtx.keccak(ByteArray(0)).toHex())
    }

    @Test fun vectors() {
        val pre = PopCtx.preimage(480, safe.drop(2).hexToBytes(), ctx.drop(2).hexToBytes(), nb, sid.hexToBytes())
        assertEquals(192, pre.size)
        assertEquals(gNonce, PopCtx.nonce(480, safe, ctx, nb, sid).toHex())
        assertEquals("9fc7507c663ae43d4f8d56ba4b805fdf9e928e565141666a47630aa7fd04b121", PopCtx.nonce(480, nSafe, nCtx, nb, sid).toHex())
        assertEquals("ab8e50bb766db52b752932e48a63148cf015ac1a17c1345c35d4765f51027d66", PopCtx.nonce(480, pool, ctx, nb, sid).toHex())
    }

    @Test fun traps() {
        assertEquals("a0b4077ef6736018b1ddbc33a5d4b3e3c28a211f1a52566e6d400f7aecd6ff8b", PopCtx.nonce(480, guard, ctx, nb, sid).toHex())
        // sid as uint128 (right-aligned) must not be what we build
        val pre = PopCtx.preimage(480, safe.drop(2).hexToBytes(), ctx.drop(2).hexToBytes(), nb, sid.hexToBytes())
        val asUint = pre.copyOf(160) + ByteArray(16) + sid.hexToBytes()
        assertEquals("a3993cf3f5bce4adc7c16d5e5c9c50e78dbde87ce9e1b933ad53fc8665440661", PopCtx.keccak(asUint).toHex())
        assertNotEquals(gNonce, PopCtx.keccak(asUint).toHex())
    }

    // ---- the gate ----

    private val chain = SafeTx.CHAIN_SEPOLIA
    private val tx = SafeTx(to = "0x" + "11".repeat(20), value = "1000")
    private val good = SafeTx.context(chain, safe, tx)

    private fun gate(context: JsonObject = good, t: SafeTx = tx, spendChain: Long = chain, spendSafe: String = safe, mySafe: String? = safe) =
        ContextGate.check(context, t.json(), spendChain, spendSafe, mySafe, chain)

    private fun code(r: ContextGate.Result) = (r as ContextGate.Result.Refused).code

    @Test fun gatePasses() {
        val ok = assertIs<ContextGate.Result.Ok>(gate())
        assertEquals(Allowlist.What.Native(tx.to, "1000"), ok.spend.what)
    }

    @Test fun gateRefuses() {
        assertEquals(ContextGate.UNKNOWN_CONSUMER, code(gate(mySafe = guard)))
        assertEquals(ContextGate.UNKNOWN_CONSUMER, code(gate(mySafe = null)))
        val mm = ContextGate.CONTEXT_MISMATCH
        assertEquals(mm, code(gate(spendChain = 480)))
        assertEquals(mm, code(gate(spendSafe = guard)))
        assertEquals(mm, code(gate(t = tx.copy(nonce = "1"))))
        assertEquals(mm, code(gate(context = JsonObject(good + ("extra" to JsonPrimitive(1))))))
        assertEquals(mm, code(gate(context = JsonObject(good + ("chain_id" to JsonPrimitive(chain.toString()))))))
        // the hash is right, the allowlist still says no
        val bad = tx.copy(operation = 1)
        assertEquals(ContextGate.CONTEXT_REFUSED, code(gate(context = SafeTx.context(chain, safe, bad), t = bad)))
    }

    @Test fun nonce() {
        val spend = (gate() as ContextGate.Result.Ok).spend
        val n = PopCtx.nonce(chain, safe, spend.ctxHash, nb, sid).toHex()
        assertTrue(ContextGate.nonceOk(spend, sid, nb, n))
        assertTrue(ContextGate.nonceOk(spend, sid, nb, "0x" + n.uppercase()))
        assertFalse(ContextGate.nonceOk(spend, sid, nb + 1, n))
        assertFalse(ContextGate.nonceOk(spend, sid, nb, null))
        assertFalse(ContextGate.nonceOk(spend, sid, null, n))
    }
}
