package com.enconomy.pop

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.toByteArray
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.jsonObject
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class WorldIdTest {
    private val jsonHdr = headersOf(HttpHeaders.ContentType, "application/json")

    @Test fun startAndStatusWire() = runTest {
        val seen = mutableListOf<String>()
        val engine = MockEngine { req ->
            val path = req.url.encodedPath + (if (req.url.encodedQuery.isNotEmpty()) "?" + req.url.encodedQuery else "")
            seen += "${req.method.value} $path ${req.body.toByteArray().decodeToString()} sig=${req.headers["X-Pop-Sig"] != null}"
            when {
                path.endsWith("/worldid/start") ->
                    respond("""{"request_id":"r1","connector_uri":"https://world.org/verify?t=wld&i=x&k=y","expires_at_s":1790000300}""", HttpStatusCode.OK, jsonHdr)
                path.contains("/worldid?") -> respond("""{"role":"B","status":"awaiting"}""", HttpStatusCode.OK, jsonHdr)
                path.endsWith("/attestation") -> respond("""{"v":1,"att":{"v":"pop-test-v1"},"att_refused":null}""", HttpStatusCode.OK, jsonHdr)
                else -> respond("""{"error":"same_human"}""", HttpStatusCode.Conflict, jsonHdr)
            }
        }
        val api = PopApi("http://h:8000", key = { FakeKey() }, engine = engine, clockSync = false)
        val r = api.worldidStart("ab")
        assertEquals("r1", r.request_id)
        assertTrue(r.connector_uri.startsWith("https://world.org/verify"))
        val st = api.worldidStatus("ab", timeoutS = 25)
        assertEquals("awaiting", st.status)
        assertNull(st.error)
        assertEquals("pop-test-v1", api.attestation("ab")["att"]!!.jsonObject["v"].toString().trim('"'))
        assertEquals("POST /v1/session/ab/worldid/start {} sig=true", seen[0])
        assertEquals("GET /v1/session/ab/worldid?timeout_s=25  sig=true", seen[1])
        assertEquals("GET /v1/session/ab/attestation  sig=false", seen[2])
        val e = assertFailsWith<PopHttpException> { api.session("ab") }
        assertEquals("same_human", e.code)
    }

    @Test fun viewHumanParsing() {
        val v = popJson.decodeFromString(SessionView.serializer(),
            """{"session_id":"ab","state":"joined","policy":{"human":"worldid"},
               "human":{"A":{"status":"verified"},"B":{"status":"failed","error":"user_rejected"},"pair_tag":null}}""")
        assertTrue(WorldId.required(v.policy))
        assertEquals(WorldId.Role("verified"), WorldId.role(v.human, "A"))
        assertEquals(WorldId.Role("failed", "user_rejected"), WorldId.role(v.human, "B"))
        assertNull(WorldId.pairTag(v.human))
        assertEquals(WorldId.Role("idle"), WorldId.role(null, "A"))
        assertFalse(WorldId.required(null))
        val none = popJson.decodeFromString(SessionView.serializer(), """{"session_id":"ab","state":"joined","policy":{"human":"none"}}""")
        assertFalse(WorldId.required(none.policy))
    }

    @Test fun errorTexts() {
        assertEquals("Both phones used the same World ID. Two different people are needed.", WorldId.errorText("same_human"))
        assertEquals("This needs an Orb-verified World ID", WorldId.errorText("human_level"))
        assertEquals("World ID request expired. Tap to retry.", WorldId.errorText("human_expired"))
        assertEquals("World ID is unreachable", WorldId.errorText("worldid_unavailable"))
        assertEquals("Cancelled in World ID. Confirm stays off.", WorldId.errorText("user_rejected"))
        assertEquals("Waiting for the other person's World ID", WorldId.errorText("human_missing"))
        assertEquals("World ID check failed. Try again.", WorldId.errorText("human_invalid"))
        assertEquals("World ID check failed. Try again.", WorldId.errorText(null))
        assertTrue(WorldId.needsNewSession("same_human"))
        assertTrue(WorldId.needsNewSession("nullifier_replayed"))
        assertFalse(WorldId.needsNewSession("human_invalid"))
        assertFalse(WorldId.needsNewSession("user_rejected"))
    }

    @Test fun returnLink() {
        assertTrue(WorldId.isReturnLink("enconomy://worldid"))
        assertTrue(WorldId.isReturnLink("enconomy://worldid?x=1"))
        assertFalse(WorldId.isReturnLink("https://world.org/verify"))
        assertFalse(WorldId.isReturnLink(null))
    }
}
