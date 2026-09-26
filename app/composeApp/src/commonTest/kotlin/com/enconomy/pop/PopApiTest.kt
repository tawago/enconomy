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

    /**
     * Proof upload = server/pop/main.py proof route: multipart, file part "proof" + JSON "meta" {attempt, circuit, salt}.
     * POP_API_DUMP=<dir> writes the body + content type (server-side parse check).
     */
    @Test fun proofUploadIsMultipart() = runTest {
        val key = FakeKey()
        var ct = ""
        var body = ByteArray(0)
        var pq = ""
        val engine = MockEngine { req ->
            ct = req.body.contentType.toString()
            body = req.body.toByteArray()
            pq = req.url.encodedPath
            respond("""{"status":"verified","role":"A","zk":{}}""", HttpStatusCode.OK, jsonHdr)
        }
        val api = PopApi("http://h:8000", key = { key }, nowMs = { 9 }, engine = engine, clockSync = false)
        val proof = ByteArray(3000) { (it * 7).toByte() }
        val out = api.uploadProof("sid1", 2, "oa2t_s48", "123456789012345678901234567890", proof)
        assertEquals("server: verified", com.enconomy.pop.zk.uploadSummary(out))
        assertEquals("/v1/session/sid1/proof", pq)
        assertTrue(ct.startsWith("multipart/form-data; boundary="), ct)
        val boundary = ct.substringAfter("boundary=")
        testEnv("POP_API_DUMP")?.let { d ->
            com.enconomy.pop.zk.ZkFiles.write("$d/proof_upload.body", body)
            com.enconomy.pop.zk.ZkFiles.write("$d/proof_upload.ct", ct.encodeToByteArray())
        }
        // parts: split on the boundary, headers \r\n\r\n body \r\n
        val text = body.decodeToString(throwOnInvalidSequence = false)
        assertTrue(text.endsWith("--$boundary--\r\n"))
        val heads = Regex("Content-Disposition: form-data; name=\"(\\w+)\"(; filename=\"[^\"]+\")?").findAll(text).map { it.groupValues }.toList()
        assertEquals(listOf("proof", "meta"), heads.map { it[1] })
        assertTrue(heads[0][2].isNotEmpty(), "proof must be a file part")
        assertTrue(heads[1][2].isEmpty(), "meta must be a plain field")
        // raw proof bytes between the proof part's header and the next boundary
        val start = indexOf(body, "\r\n\r\n".encodeToByteArray(), indexOf(body, "name=\"proof\"".encodeToByteArray(), 0)) + 4
        assertContentEquals(proof, body.copyOfRange(start, start + proof.size))
        assertEquals("\r\n--$boundary", body.copyOfRange(start + proof.size, start + proof.size + boundary.length + 4).decodeToString())
        val meta = popJson.parseToJsonElement(text.substringAfter("name=\"meta\"\r\n\r\n").substringBefore("\r\n--$boundary")).toString()
        assertEquals("""{"attempt":2,"circuit":"oa2t_s48","salt":"123456789012345678901234567890"}""", meta)
        // signature covers the exact multipart bytes
        assertContentEquals(requestMessage("POST", "/v1/session/sid1/proof", body, 9), key.signed.single())
    }

    @Test fun proofUploadStatusNotes() {
        fun note(st: Int, code: String?) = com.enconomy.pop.zk.proofUploadNote(PopHttpException(st, code, ""))
        assertEquals("server: verified (already submitted)", note(409, "already_submitted"))
        assertTrue(note(503, "zk_unavailable").contains("kept on the phone"))
        assertTrue(note(400, "bad_attempt").contains("bad_attempt"))
        assertTrue(note(409, "bad_state").contains("bad_state"))
    }

    private fun indexOf(h: ByteArray, n: ByteArray, from: Int): Int {
        for (i in from..h.size - n.size) if ((n.indices).all { h[i + it] == n[it] }) return i
        return -1
    }

    // ---- resume after suspension (iPhone back from World App) ----

    /** Server with the §2.3 replay cache on (device, ts, sig). */
    private class ReplayServer(var serverMs: () -> Long) {
        val seen = mutableSetOf<Pair<String, String>>()
        val paths = mutableListOf<String>()
        val tss = mutableListOf<Long>()
        val engine = MockEngine { req ->
            paths += req.url.encodedPath
            if (req.url.encodedPath == "/v1/time") return@MockEngine respond("""{"server_ms":${serverMs()}}""", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            val ts = req.headers["X-Pop-Ts"]!!
            tss += ts.toLong()
            val body = when {
                kotlin.math.abs(ts.toLong() - serverMs()) > 60_000 -> """{"error":"auth_stale"}"""
                !seen.add(ts to req.headers["X-Pop-Sig"]!!) -> """{"error":"auth_replay"}"""
                else -> null
            }
            if (body != null) respond(body, HttpStatusCode.Unauthorized, headersOf(HttpHeaders.ContentType, "application/json"))
            else if (req.url.encodedPath.endsWith("/worldid")) respond("""{"status":"verified"}""", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            else respond("""{"session_id":"s","seq":9,"state":"joined"}""", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }
    }

    /** The OS re-sent our earlier bytes (same ts + sig) -> auth_replay -> resync, fresh signature, 200. */
    @Test fun replayIsResignedAndRetried() = runTest {
        val srv = ReplayServer { 1_005_000L }
        val key = FakeKey()
        val api = PopApi("http://h:8000", key = { key }, nowMs = { 1_000_000L }, engine = srv.engine)
        api.worldidStatus("s", timeoutS = 25)
        val ts0 = srv.tss.single()
        assertEquals(1_005_000L, ts0)
        // the bytes the next call will carry already reached the server (iOS resent them on resume)
        val ts1 = ts0 + 1
        srv.seen += ts1.toString() to signRequest(key, "GET", "/v1/session/s/worldid?timeout_s=25", ByteArray(0), ts1).sig
        assertEquals("verified", api.worldidStatus("s", timeoutS = 25).status)
        assertEquals(listOf(ts0, ts1, ts1 + 1), srv.tss)
        assertEquals(listOf("/v1/time", "/v1/session/s/worldid", "/v1/session/s/worldid", "/v1/time", "/v1/session/s/worldid"), srv.paths)
    }

    /** Two parallel requests in the same wall ms never share X-Pop-Ts (deterministic signer = same sig otherwise). */
    @Test fun sameMsRequestsGetDistinctTs() = runTest {
        val srv = ReplayServer { 1_000L }
        val api = PopApi("http://h:8000", key = { FakeKey() }, nowMs = { 1_000L }, engine = srv.engine)
        repeat(3) { api.session("s", after = 8, timeoutS = 5) }
        assertEquals(3, srv.tss.toSet().size)
        assertEquals(listOf("/v1/time", "/v1/session/s", "/v1/session/s", "/v1/session/s"), srv.paths)
    }

    /** Suspended 10 min: X-Pop-Ts follows the wall clock, no resync needed; invalidateClock forces one. */
    @Test fun tsFollowsWallAcrossSuspendAndResyncOnForeground() = runTest {
        var wall = 1_000_000L
        val srv = ReplayServer { wall + 42_000L }
        val api = PopApi("http://h:8000", key = { FakeKey() }, nowMs = { wall }, engine = srv.engine)
        api.session("s")
        wall += 600_000L
        api.session("s")
        assertEquals(wall + 42_000L, srv.tss.last())
        assertEquals(1, srv.paths.count { it == "/v1/time" })
        api.invalidateClock()
        api.session("s")
        assertEquals(2, srv.paths.count { it == "/v1/time" })
    }

    @Test fun unknownDeviceIsNotRetried() = runTest {
        var calls = 0
        val engine = MockEngine { req ->
            if (req.url.encodedPath == "/v1/time") return@MockEngine respond("""{"server_ms":5}""", HttpStatusCode.OK, jsonHdr)
            calls++
            respond("""{"error":"auth_unknown_device"}""", HttpStatusCode.Unauthorized, jsonHdr)
        }
        val api = PopApi("http://h:8000", key = { FakeKey() }, nowMs = { 5 }, engine = engine)
        assertEquals("auth_unknown_device", assertFailsWith<PopHttpException> { api.session("s") }.code)
        assertEquals(1, calls)
    }

    @Test fun onCloseCallback() {
        var closed: PopApi? = null
        val api = PopApi("http://h:8000", engine = MockEngine { respond("{}") }, onClose = { closed = it })
        api.close()
        assertEquals(api, closed)
    }
}
