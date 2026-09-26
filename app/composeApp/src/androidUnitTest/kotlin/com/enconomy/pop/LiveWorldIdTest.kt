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

    /**
     * B takes the sandbox path (World ID Simulator request, nullifier accepted unverified; server needs
     * POP_WORLDID_SANDBOX=1), A the normal one. B starts its run right after its own confirm, while the session
     * is still "joined" (what the app did when the confirm view already carried the nonce); A confirms later.
     */
    @Test fun sandboxRoleThenNear() = live { a, b ->
        if (sameHumanSidecar) { println("same-human sidecar, skipping"); return@live }
        val apiA = PopApi(url!!, key = { a }); val apiB = PopApi(url, key = { b })
        try {
            val sid = pairWithContext(apiA, apiB)
            val rb0 = apiB.worldidStart(sid, sandbox = true)
            assertTrue(rb0.connector_uri.startsWith("https://simulator.worldcoin.org/?connect_url="), rb0.connector_uri)
            val (sa, sb) = coroutineScope {
                val x = async(Dispatchers.Default) { worldId(apiA, sid) }
                val y = async(Dispatchers.Default) { pollOwn(apiB, sid) }
                x.await() to y.await()
            }
            assertEquals(WorldId.VERIFIED, sa.status, "$sa")
            assertEquals(WorldId.VERIFIED, sb.status, "$sb")
            val view = apiA.session(sid)
            assertTrue(WorldId.role(view.human, "B").sandbox, "${view.human}")
            assertTrue(!WorldId.role(view.human, "A").sandbox, "${view.human}")
            assertNotNull(WorldId.pairTag(view.human))

            val air = Air(30.0)
            val (ra, rb) = coroutineScope {
                val y = async(Dispatchers.Default) {
                    val v0 = apiB.confirm(sid)
                    println("B confirm -> state ${v0.state} nonce ${v0.nonce != null}")
                    PopRun(apiB, FakeEngine(air, 'B'), b, sid, 'B').run()
                }
                val x = async(Dispatchers.Default) {
                    kotlinx.coroutines.delay(1500)
                    apiA.confirm(sid)
                    PopRun(apiA, FakeEngine(air, 'A'), a, sid, 'A').run()
                }
                x.await() to y.await()
            }
            println("sandbox run: ${ra.verdict} ${ra.flight_cm} cm")
            assertEquals("NEAR", ra.verdict, "$ra")
            assertEquals(ra, rb)
        } finally { apiA.close(); apiB.close() }
    }

    private suspend fun pollOwn(api: PopApi, sid: String): WorldIdStatusResp {
        while (true) {
            val st = api.worldidStatus(sid, timeoutS = 25)
            if (st.status == WorldId.VERIFIED || st.status == WorldId.FAILED) return st
        }
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
            // retry with the same human: the nullifier is still taken by A -> same_human again, A stays verified
            val sb2 = worldId(apiB, sid)
            assertEquals("same_human", sb2.error, "$sb2")
            assertEquals(WorldId.VERIFIED, WorldId.role(apiA.session(sid).human, "A").status)
            // even with both confirms in, the arm gate holds (§7.2)
            apiA.confirm(sid); apiB.confirm(sid)
            assertEquals("human_missing", assertFailsWith<PopHttpException> { apiA.arm(sid, ArmReq(0, 48000, 5.0)) }.code)
        } finally { apiA.close(); apiB.close() }
    }

    /** A tampered context (other ctx_hash, other consumer, other nonce) fails the phone gate; a wrong chain fails create. */
    @Test fun contextMismatchRefused() = live { a, _ ->
        val apiA = PopApi(url!!, key = { a })
        try {
            val ctx = buildJsonObject {
                put("kind", JsonPrimitive("test")); put("chain_id", JsonPrimitive(4801L))
                put("consumer", JsonPrimitive("0x" + "5afe".repeat(10)))
                put("ctx_hash", JsonPrimitive("0x" + "ab".repeat(32)))
            }
            val inv = apiA.createSession(SessionReq(context = ctx))
            assertTrue(ContextGate.check(inv.session_id, ctx, inv.not_before, inv.nonce, allowTestKind = true) is ContextGate.Result.Ok)
            val other = JsonObject(ctx + ("ctx_hash" to JsonPrimitive("0x" + "cd".repeat(32))))
            val r1 = ContextGate.check(inv.session_id, other, inv.not_before, inv.nonce, allowTestKind = true)
            assertEquals(ContextGate.CONTEXT_MISMATCH, (r1 as ContextGate.Result.Refused).code)
            val r2 = ContextGate.check(inv.session_id, ctx, inv.not_before!! + 1, inv.nonce, allowTestKind = true)
            assertEquals(ContextGate.CONTEXT_MISMATCH, (r2 as ContextGate.Result.Refused).code)
            val r3 = ContextGate.check(inv.session_id, ctx, inv.not_before, inv.nonce, allowTestKind = false)
            assertTrue(r3 is ContextGate.Result.Refused, "test kind refused in a release build")
            val bad = JsonObject(ctx + ("chain_id" to JsonPrimitive(1L)))
            val e = assertFailsWith<PopHttpException> { apiA.createSession(SessionReq(context = bad)) }
            println("wrong chain -> ${e.status} ${e.code}")
            assertTrue(e.status in 400..499, "${e.status} ${e.code}")
        } finally { apiA.close() }
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
            val samples = listOf(12000L, 11900L, 12100L, 12050L, 11950L)
            val c = CalibrationReq(Calibration.fromSamples(samples), 48000, "speaker", "aaudio", samples)
            val r = api.enroll(EnrollReq(n, k.deviceId, k.pubkey.toHex(), name, "jvm", "software", null,
                calibration = c, cal_sig_b64 = k.sign(Calibration.message(n, c)).toB64()))
            assertEquals(12000L, r.calibration?.cal_us)
        } finally { api.close() }
    }

}
