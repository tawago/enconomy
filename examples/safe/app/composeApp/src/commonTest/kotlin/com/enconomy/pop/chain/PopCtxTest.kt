package com.enconomy.pop.chain

import com.enconomy.pop.hexToBytes
import com.enconomy.pop.toHex
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotEquals

/** docs/worldid/01 §5 golden vectors (VERIFIED there with pycryptodome, forge, cast). */
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

    @Test fun gVector() {
        val pre = PopCtx.preimage(480, safe.drop(2).hexToBytes(), ctx.drop(2).hexToBytes(), nb, sid.hexToBytes())
        assertEquals(192, pre.size)
        val n = PopCtx.nonce(480, safe, ctx, nb, sid)
        assertEquals(gNonce, n.toHex())
        assertEquals("0x${gNonce}41", PopCtx.signalHex(n, 'A'))
        assertEquals("0x002916db5141cfe5584c6de9cf6f45579e83422ecdf3260c31e30bc7f2b964c6", PopCtx.signalHash(n, 'A'))
        assertEquals("0x0097c2b664c193be4b2699e4224cd1c6c3bb1f8de93919ebee7d7e346f25ff2b", PopCtx.signalHash(n, 'B'))
    }

    @Test fun nVector() {
        val n = PopCtx.nonce(480, nSafe, nCtx, nb, sid)
        assertEquals("9fc7507c663ae43d4f8d56ba4b805fdf9e928e565141666a47630aa7fd04b121", n.toHex())
        assertEquals("0x008f770c3f6700ffa8277d98ae286f59448b26c40ecc9b59eb4236aec76f5637", PopCtx.signalHash(n, 'A'))
        assertEquals("0x00e9c210433251df53d3a8650bc8f0b54e5ad84ffcc0593e2785d0778f92199a", PopCtx.signalHash(n, 'B'))
    }

    @Test fun poolAndAction() {
        assertEquals("ab8e50bb766db52b752932e48a63148cf015ac1a17c1345c35d4765f51027d66", PopCtx.nonce(480, pool, ctx, nb, sid).toHex())
        assertEquals("pop:$sid", PopCtx.action(sid))
        assertEquals("0x003d0a5a51f4fe9954190e3c33adb92f760da336203f33ee63a29ad4ee6fd8ae", PopCtx.actionField(PopCtx.action(sid)))
    }

    @Test fun traps() {
        assertEquals("a0b4077ef6736018b1ddbc33a5d4b3e3c28a211f1a52566e6d400f7aecd6ff8b", PopCtx.nonce(480, guard, ctx, nb, sid).toHex())
        // sid as uint128 (right-aligned) must not be what we build
        val pre = PopCtx.preimage(480, safe.drop(2).hexToBytes(), ctx.drop(2).hexToBytes(), nb, sid.hexToBytes())
        val asUint = pre.copyOf(160) + ByteArray(16) + sid.hexToBytes()
        assertEquals("a3993cf3f5bce4adc7c16d5e5c9c50e78dbde87ce9e1b933ad53fc8665440661", PopCtx.keccak(asUint).toHex())
        assertNotEquals(gNonce, PopCtx.keccak(asUint).toHex())
    }

    // ---- context gate ----

    private fun context(kind: String = "test", consumer: String = safe, ctxHash: String = ctx, chainId: Long = 480): JsonObject =
        buildJsonObject { put("kind", kind); put("chain_id", chainId); put("consumer", consumer); put("ctx_hash", ctxHash) }

    @Test fun gatePassesMatchingNonce() {
        val r = ContextGate.check(sid, context(), nb, "0x$gNonce", allowTestKind = true)
        assertEquals(ContextGate.Result.Ok("0x$gNonce", "test", safe, ctx), r)
        assertIs<ContextGate.Result.Ok>(ContextGate.check(sid, context(), nb, gNonce.uppercase(), allowTestKind = true))
    }

    @Test fun gateNoContext() {
        assertEquals(ContextGate.Result.NoContext, ContextGate.check(sid, null, null, "ab".repeat(32)))
    }

    @Test fun gateRefusesMismatch() {
        fun code(r: ContextGate.Result) = (r as ContextGate.Result.Refused).code
        val mm = ContextGate.CONTEXT_MISMATCH
        // server swapped one input: nonce no longer matches
        assertEquals(mm, code(ContextGate.check(sid, context(), nb + 1, "0x$gNonce", allowTestKind = true)))
        assertEquals(mm, code(ContextGate.check(sid, context(consumer = guard), nb, "0x$gNonce", allowTestKind = true)))
        assertEquals(mm, code(ContextGate.check(sid, context(chainId = 4801), nb, "0x$gNonce", allowTestKind = true)))
        assertEquals(mm, code(ContextGate.check("ff" + sid.drop(2), context(), nb, "0x$gNonce", allowTestKind = true)))
        assertEquals(mm, code(ContextGate.check(sid, context(), nb, null, allowTestKind = true)))
        assertEquals(mm, code(ContextGate.check(sid, context(), null, "0x$gNonce", allowTestKind = true)))
        // shape: uppercase consumer, chain_id as string
        assertEquals(mm, code(ContextGate.check(sid, context(consumer = safe.uppercase().replace("0X", "0x")), nb, "0x$gNonce", allowTestKind = true)))
        val strChain = JsonObject(context() + ("chain_id" to JsonPrimitive("480")))
        assertEquals(mm, code(ContextGate.check(sid, strChain, nb, "0x$gNonce", allowTestKind = true)))
    }

    @Test fun gateConsumerAndKind() {
        fun code(r: ContextGate.Result) = (r as ContextGate.Result.Refused).code
        // test kind is off outside debug builds
        assertEquals(ContextGate.UNKNOWN_CONSUMER, code(ContextGate.check(sid, context(), nb, "0x$gNonce", allowTestKind = false)))
        // a real kind: consumer must be known, then the kind must recompute ctx_hash
        val n = "0x" + PopCtx.nonce(480, nSafe, nCtx, nb, sid).toHex()
        val c = context(kind = "safe-tx", consumer = nSafe, ctxHash = nCtx)
        assertEquals(ContextGate.UNKNOWN_CONSUMER, code(ContextGate.check(sid, c, nb, n, knownConsumers = setOf(safe))))
        assertEquals(ContextGate.CONTEXT_MISMATCH, code(ContextGate.check(sid, c, nb, n, knownConsumers = setOf(nSafe))))
        assertEquals(ContextGate.CONTEXT_MISMATCH, code(ContextGate.check(sid, c, nb, n, knownConsumers = setOf(nSafe)) { _, _ -> ctx }))
        assertIs<ContextGate.Result.Ok>(ContextGate.check(sid, c, nb, n, knownConsumers = setOf(nSafe.uppercase())) { _, _ -> nCtx })
    }
}
