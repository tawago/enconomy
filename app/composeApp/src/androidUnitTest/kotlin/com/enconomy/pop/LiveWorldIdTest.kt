package com.enconomy.pop

import com.enconomy.pop.chain.ContextGate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * docs/worldid/01 §6.10: create with a `test` context -> context gate on both phones -> /worldid/start for both
 * roles -> long-poll until verified -> the simulated audio pair to NEAR -> attestation pop-test-v1.
 * Needs POP_LIVE_URL and a server with POP_TEST_KINDS=1 POP_WORLDID_FAKE=1 plus the fake sidecar.
 * sameHuman needs the sidecar started with FAKE_SAME_HUMAN=1 and POP_LIVE_SAME_HUMAN=1 here.
 */
class LiveWorldIdTest {
    private val url = System.getenv("POP_LIVE_URL")?.takeIf { it.isNotBlank() }
    private val sameHumanSidecar = System.getenv("POP_LIVE_SAME_HUMAN") == "1"

    @Test fun worldIdThenNearThenAttestation() = live { a, b ->
        if (sameHumanSidecar) { println("same-human sidecar, skipping"); return@live }
        val apiA = PopApi(url!!, key = { a }); val apiB = PopApi(url, key = { b })
        try {
            val sid = pairWithContext(apiA, apiB)
            // Confirm stays blocked: arm before World ID -> human_missing
            val early = assertFailsWith<PopHttpException> { apiA.arm(sid, ArmReq(0, 48000, 5.0)) }
            assertTrue(early.code == "human_missing" || early.code == "bad_state", "${early.code}")
            val (sa, sb) = coroutineScope {
                val x = async(Dispatchers.Default) { worldId(apiA, sid) }
                val y = async(Dispatchers.Default) { worldId(apiB, sid) }
                x.await() to y.await()
            }
            assertEquals(WorldId.VERIFIED, sa.status, "$sa")
            assertEquals(WorldId.VERIFIED, sb.status, "$sb")
            // a second start on a verified role: already_verified (the app shows verified)
            assertEquals("already_verified", assertFailsWith<PopHttpException> { apiA.worldidStart(sid) }.code)
            val view = apiA.session(sid)
            assertEquals(WorldId.VERIFIED, WorldId.role(view.human, "A").status)
            assertEquals(WorldId.VERIFIED, WorldId.role(view.human, "B").status)
            assertNotNull(WorldId.pairTag(view.human))

            apiA.confirm(sid); apiB.confirm(sid)
            val air = Air(30.0)
            val (ra, rb) = coroutineScope {
                val x = async(Dispatchers.Default) { PopRun(apiA, FakeEngine(air, 'A'), a, sid, 'A').run() }
                val y = async(Dispatchers.Default) { PopRun(apiB, FakeEngine(air, 'B'), b, sid, 'B').run() }
                x.await() to y.await()
            }
            assertEquals("NEAR", ra.verdict, "$ra")
            assertEquals(ra, rb)
            assertNotNull(ra.pair_tag ?: WorldId.pairTag(ra.human), "result carries the pair tag")
            // S3 (attestation endpoint) is its own server step: a server without it answers 404
            val att = try { apiA.attestation(sid) } catch (e: PopHttpException) {
                if (e.status == 404 && e.code == "not_found") { println("no /attestation on this server (S3 not landed), skipping"); return@live }
                throw e
            }
            println("attestation ${att.toString().take(400)}")
            assertEquals("pop-test-v1", att["att"]?.jsonObject?.get("v")?.jsonPrimitive?.content, "$att")
            assertTrue(att["att_refused"] == null || att["att_refused"].toString() == "null", "$att")
        } finally { apiA.close(); apiB.close() }
    }

    @Test fun sameHumanRefused() = live { a, b ->
        if (!sameHumanSidecar) { println("POP_LIVE_SAME_HUMAN unset, skipping"); return@live }
        val apiA = PopApi(url!!, key = { a }); val apiB = PopApi(url, key = { b })
        try {
            val sid = pairWithContext(apiA, apiB)
            val sa = worldId(apiA, sid)
            assertEquals(WorldId.VERIFIED, sa.status)
            val sb = worldId(apiB, sid)
            assertEquals(WorldId.FAILED, sb.status, "$sb")
            assertEquals("same_human", sb.error)
            assertTrue(WorldId.needsNewSession(sb.error))
            // even with both confirms in, the arm gate holds (§7.2)
            apiA.confirm(sid); apiB.confirm(sid)
            assertEquals("human_missing", assertFailsWith<PopHttpException> { apiA.arm(sid, ArmReq(0, 48000, 5.0)) }.code)
        } finally { apiA.close(); apiB.close() }
    }

    /** Host creates with a test context, guest joins; both phones run the context gate like the app. */
    private suspend fun pairWithContext(apiA: PopApi, apiB: PopApi): String {
        val cfg = apiA.config()
        val chainId = (cfg["chain"] as? JsonObject)?.get("chain_id")?.jsonPrimitive?.longOrNull ?: 4801L
        val ctx = buildJsonObject {
            put("kind", JsonPrimitive("test")); put("chain_id", JsonPrimitive(chainId))
            put("consumer", JsonPrimitive("0x" + "5afe".repeat(10)))
            put("ctx_hash", JsonPrimitive("0x" + secureRandomBytes(32).toHex()))
        }
        val inv = apiA.createSession(SessionReq(context = ctx))
        assertTrue(WorldId.required(inv.policy), "${inv.policy}")
        assertTrue(ContextGate.check(inv.session_id, ctx, inv.not_before, inv.nonce, allowTestKind = true) is ContextGate.Result.Ok)
        // before the guest joined: not_joined
        assertEquals("not_joined", assertFailsWith<PopHttpException> { apiA.worldidStart(inv.session_id) }.code)
        val v = apiB.join(inv.session_id, inv.join_token)
        assertTrue(WorldId.required(v.policy), "${v.policy}")
        assertTrue(ContextGate.check(inv.session_id, v.context, v.not_before, v.nonce, allowTestKind = true) is ContextGate.Result.Ok)
        return inv.session_id
    }

    /** What the app does: start once, then long-poll own status until terminal. */
    private suspend fun worldId(api: PopApi, sid: String): WorldIdStatusResp {
        val r = api.worldidStart(sid)
        assertTrue(r.connector_uri.isNotBlank())
        // start again inside 240 s: same request (one request serves both buttons)
        assertEquals(r.connector_uri, api.worldidStart(sid).connector_uri)
        while (true) {
            val st = api.worldidStatus(sid, timeoutS = 25)
            if (st.status == WorldId.VERIFIED || st.status == WorldId.FAILED) return st
        }
    }

    private fun live(body: suspend (JvmKey, JvmKey) -> Unit) {
        if (url == null) { println("POP_LIVE_URL unset, skipping"); return }
        runBlocking {
            val a = JvmKey(); val b = JvmKey()
            enroll(a, "host"); enroll(b, "guest")
            withTimeout(90_000) { body(a, b) }
        }
    }

    private suspend fun enroll(k: JvmKey, name: String) {
        val api = PopApi(url!!)
        try {
            val n = api.enrollNonce().nonce
            api.enroll(EnrollReq(n, k.deviceId, k.pubkey.toHex(), name, "jvm", "software", null))
        } finally { api.close() }
    }

}
