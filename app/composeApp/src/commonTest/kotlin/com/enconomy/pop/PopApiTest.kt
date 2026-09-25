package com.enconomy.pop

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.toByteArray
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PopApiTest {
    private val jsonHdr = headersOf(HttpHeaders.ContentType, "application/json")

    @Test fun signedPostHeadersMatchBody() = runTest {
        val key = FakeKey()
        var seen: Triple<String, String, ByteArray>? = null
        var hdr: Map<String, String?> = emptyMap()
        val engine = MockEngine { req ->
            val body = req.body.toByteArray()
            seen = Triple(req.method.value, req.url.encodedPath + "?" + req.url.encodedQuery, body)
            hdr = listOf("X-Pop-Device", "X-Pop-Ts", "X-Pop-Sig").associateWith { req.headers[it] }
            respond("""{"session_id":"ab","seq":3,"state":"joined","attempt":0}""", HttpStatusCode.OK, jsonHdr)
        }
        val api = PopApi("http://h:8000/", key = { key }, nowMs = { 1790000000123 }, engine = engine)
        val v = api.join("ab", "tok")
        assertEquals("joined", v.state)
        val (m, pq, body) = seen!!
        assertEquals("POST", m)
        assertEquals("/v1/session/ab/join?", pq)
        assertEquals("""{"join_token":"tok"}""", body.decodeToString())
        assertEquals(key.deviceId, hdr["X-Pop-Device"])
        assertEquals("1790000000123", hdr["X-Pop-Ts"])
        val msg = requestMessage("POST", "/v1/session/ab/join", body, 1790000000123)
        assertContentEquals(msg, key.signed.single())
        assertContentEquals(key.sign(msg), hdr["X-Pop-Sig"]!!.fromB64())
    }

    @Test fun longPollSignsQuery() = runTest {
        val key = FakeKey()
        val engine = MockEngine { respond("""{"session_id":"ab","seq":8,"state":"started","t0_ms":5}""", HttpStatusCode.OK, jsonHdr) }
        val api = PopApi("http://h:8000", key = { key }, nowMs = { 7 }, engine = engine)
        val v = api.session("ab", after = 7, timeoutS = 25)
        assertEquals(5L, v.t0_ms)
        val s = key.signed.single().decodeToString()
        assertTrue(s.startsWith("pop-req-v1\nGET\n/v1/session/ab?after=7&timeout_s=25\ne3b0c442"), s)
    }

    @Test fun unsignedEnrollSendsNullChain() = runTest {
        var body = ""
        var sig: String? = "x"
        val engine = MockEngine { req ->
            body = req.body.toByteArray().decodeToString()
            sig = req.headers["X-Pop-Sig"]
            respond("""{"device_id":"d","attested":false,"enrolled_at":"2026-09-26T00:00:00Z"}""", HttpStatusCode.OK, jsonHdr)
        }
        val api = PopApi("http://h:8000", engine = engine)
        api.enroll(EnrollReq("n", "d", "04", "me", "Pixel", "tee", null))
        assertNull(sig)
        assertTrue(body.contains("\"chain\":null"), body)
    }

    @Test fun errorCodeParsed() = runTest {
        val engine = MockEngine { respond("""{"error":"auth_stale","detail":"ts"}""", HttpStatusCode.Unauthorized, jsonHdr) }
        val api = PopApi("http://h:8000", key = { FakeKey() }, engine = engine)
        val e = assertFailsWith<PopHttpException> { api.createSession() }
        assertEquals(401, e.status)
        assertEquals("auth_stale", e.code)
    }
}
