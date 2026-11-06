package com.enconomy.pop

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.toByteArray
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Wire of this example's backend: examples/world-id/README.md, backend/main.py. Never run so far, like the rest of this copy. */
class WorldIdTest {
    private val jsonHdr = headersOf(HttpHeaders.ContentType, "application/json")

    /** json.dumps(sort_keys=True, separators=(",", ":")) of the same five fields. */
    @Test fun deviceCanonicalIsSorted() {
        assertEquals(
            """{"pubkey":"04ab","role":"A","session_id":"cd","session_nonce":"ef","ts":1790000003000}""",
            widDeviceCanonical("ef", "cd", "A", "04ab", 1790000003000),
        )
    }

    @Test fun startAndStatusAreSelfSigned() = runTest {
        val bodies = mutableListOf<Pair<String, String>>()
        val engine = MockEngine { req ->
            bodies += req.url.encodedPath to req.body.toByteArray().decodeToString()
            assertNull(req.headers["X-Pop-Sig"])
            if (req.url.encodedPath.endsWith("/start"))
                respond("""{"request_id":"r1","connector_uri":"https://world.org/verify?t=wld","expires_at_s":1790000300,"status":"requested"}""", HttpStatusCode.OK, jsonHdr)
            else respond("""{"role":"A","status":"verified","error":null,"partner":{"status":"awaiting"}}""", HttpStatusCode.OK, jsonHdr)
        }
        val key = FakeKey()
        val api = WorldIdApi("http://h:8300/", key = { key }, nowMs = { 7L }, engine = engine)
        assertEquals("r1", api.start("ef", "cd", "A").request_id)
        val st = api.status("ef", "cd", "A")
        assertEquals("verified", st.status)
        assertEquals("awaiting", st.partner.status)

        assertEquals(listOf("/v1/worldid/start", "/v1/worldid/status"), bodies.map { it.first })
        val b = popJson.parseToJsonElement(bodies[0].second).jsonObject
        assertEquals(setOf("session_nonce", "session_id", "role", "pubkey", "ts", "sig_b64"), b.keys)
        assertEquals(key.pubkey.toHex(), b["pubkey"]!!.jsonPrimitive.content)
        val canon = widDeviceCanonical("ef", "cd", "A", key.pubkey.toHex(), 7L)
        assertEquals(WID_DEVICE_TAG + canon, key.signed.first().decodeToString())
    }

    @Test fun recordSendsThePresenceAsIsAndReadsTheAnswer() = runTest {
        var sent = ""
        val engine = MockEngine { req ->
            sent = req.body.toByteArray().decodeToString()
            respond("""{"met":false,"reason":"same_human","session_id":"cd","session_nonce":"ef","finished_at":"x","flight_cm":"30.37","trust_tier":{"A":"tee","B":null}}""", HttpStatusCode.OK, jsonHdr)
        }
        val presence = JsonObject(mapOf("body" to JsonObject(mapOf("verdict" to JsonPrimitive("NEAR"))), "sig_b64" to JsonPrimitive("c2ln")))
        val a = WorldIdApi("http://h:8300", key = { null }, engine = engine).record(presence)
        assertEquals(presence.toString(), sent)
        assertFalse(a.met)
        assertEquals("same_human", a.reason)
        assertEquals("30.37", a.flight_cm)
    }

    @Test fun refusalsKeepTheBackendCode() = runTest {
        val engine = MockEngine { respond("""{"error":"bad_record_signature","detail":"not signed by the core"}""", HttpStatusCode.Unauthorized, jsonHdr) }
        val e = assertFailsWith<PopHttpException> { WorldIdApi("http://h:8300", key = { null }, engine = engine).record(JsonObject(emptyMap())) }
        assertEquals(401, e.status)
        assertEquals("bad_record_signature", e.code)
    }

    @Test fun confirmWaitsForBothRoles() {
        assertFalse(WidUi(status = WorldId.VERIFIED, partnerStatus = "awaiting").bothVerified)
        assertFalse(WidUi(status = "awaiting", partnerStatus = WorldId.VERIFIED).bothVerified)
        assertTrue(WidUi(status = WorldId.VERIFIED, partnerStatus = WorldId.VERIFIED).bothVerified)
    }

    @Test fun returnLinkAndNewSessionCodes() {
        assertTrue(WorldId.isReturnLink("enconomy://worldid?x=1"))
        assertFalse(WorldId.isReturnLink("enconomy://other"))
        assertTrue(WorldId.needsNewSession("same_human"))
        assertTrue(WorldId.needsNewSession("nullifier_used"))
        assertFalse(WorldId.needsNewSession("human_expired"))
    }
}
