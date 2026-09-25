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
            if (req.url.encodedPath == "/v1/time") return@MockEngine respond("""{"server_ms":1790000000123}""", HttpStatusCode.OK, jsonHdr)
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
        val api = PopApi("http://h:8000", key = { key }, nowMs = { 7 }, engine = engine, clockSync = false)
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
        val api = PopApi("http://h:8000", key = { FakeKey() }, engine = engine, clockSync = false)
        val e = assertFailsWith<PopHttpException> { api.createSession() }
        assertEquals(401, e.status)
        assertEquals("auth_stale", e.code)
    }

    /** Wall clock 5 min behind; /v1/time answered mid-rtt. */
    @Test fun clockOffsetFromTimeMidpoint() = runTest {
        var wall = 1_000_000L
        val server = { wall + 300_000L }
        val paths = mutableListOf<String>()
        var ts: String? = null
        val engine = MockEngine { req ->
            paths += req.url.encodedPath
            if (req.url.encodedPath == "/v1/time") {
                wall += 40 // request leg
                val body = """{"server_ms":${server()}}"""
                wall += 60 // response leg
                respond(body, HttpStatusCode.OK, jsonHdr)
            } else {
                ts = req.headers["X-Pop-Ts"]
                respond("""{"session_id":"s","join_token":"t","expires_at_ms":1}""", HttpStatusCode.OK, jsonHdr)
            }
        }
        val api = PopApi("http://h:8000", key = { FakeKey() }, nowMs = { wall }, engine = engine)
        api.createSession()
        // t0 = 1_000_000, server = 1_300_040, t1 = 1_000_100 -> offset = 1_300_040 - 1_000_050
        assertEquals(299_990L, api.clockOffsetMs)
        assertEquals((wall + 299_990L).toString(), ts)
        api.createSession()
        assertEquals(listOf("/v1/time", "/v1/session", "/v1/session"), paths)
    }

    @Test fun authStaleResyncsAndRetries() = runTest {
        var skew = 0L // server - wall; jumps after the first sync
        var timeCalls = 0
        var calls = 0
        val engine = MockEngine { req ->
            if (req.url.encodedPath == "/v1/time") {
                timeCalls++
                return@MockEngine respond("""{"server_ms":${1_000L + skew}}""", HttpStatusCode.OK, jsonHdr)
            }
            calls++
            val t = req.headers["X-Pop-Ts"]!!.toLong()
            if (kotlin.math.abs(t - (1_000L + skew)) > 60_000) respond("""{"error":"auth_stale"}""", HttpStatusCode.Unauthorized, jsonHdr)
            else respond("""{"session_id":"s","join_token":"t","expires_at_ms":1}""", HttpStatusCode.OK, jsonHdr)
        }
        val api = PopApi("http://h:8000", key = { FakeKey() }, nowMs = { 1_000L }, engine = engine)
        api.createSession()
        assertEquals(1, timeCalls)
        skew = 120_000L // phone clock drifted (or server restarted elsewhere)
        api.createSession()
        assertEquals(2, timeCalls)
        assertEquals(120_000L, api.clockOffsetMs)
        assertEquals(3, calls)
    }

    @Test fun authStaleAfterResyncSaysClockIsOff() = runTest {
        val engine = MockEngine { req ->
            if (req.url.encodedPath == "/v1/time") respond("""{"server_ms":5}""", HttpStatusCode.OK, jsonHdr)
            else respond("""{"error":"auth_stale","detail":"ts"}""", HttpStatusCode.Unauthorized, jsonHdr)
        }
        val api = PopApi("http://h:8000", key = { FakeKey() }, nowMs = { 5 }, engine = engine)
        val e = assertFailsWith<PopHttpException> { api.createSession() }
        assertEquals("auth_stale", e.code)
        assertEquals(CLOCK_OFF_TEXT, e.hint)
        assertEquals(CLOCK_OFF_TEXT, e.message)
    }
}
