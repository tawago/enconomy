package com.enconomy.pop

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.toByteArray
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** Arm loses the race with the partner's /fail: 400 bad_attempt -> re-read the view, re-arm at the new attempt. */
class RunArmRaceTest {
    private val jsonHdr = headersOf(HttpHeaders.ContentType, "application/json")
    private val nonce = "11".repeat(32)
    private val pk = "04" + "22".repeat(64)

    private fun view(state: String, attempt: Int, extra: String = "") =
        """{"session_id":"s","seq":${attempt + 1},"state":"$state","attempt":$attempt,"nonce":"$nonce","partner":{"device_id":"p","pubkey":"$pk"}$extra}"""

    private class NoAudio : AudioEngine {
        override fun preflight() = AudioPreflight(48000, 15, 15, null, true, true, 10.0, emptyList(), emptyList())
        override fun setMediaVolume(frac: Double) {}
        override fun prepare(sr: Int, play: FloatArray) = error("must not prepare")
        override suspend fun run(plan: RunPlan): Capture = error("must not run")
        override fun release() {}
    }

    private fun run(sessionViews: MutableList<String>, armed: MutableList<Int>, calls: MutableList<String>): PopRun {
        val engine = MockEngine { req ->
            calls += "${req.method.value} ${req.url.encodedPath}"
            when {
                req.method == HttpMethod.Post && req.url.encodedPath.endsWith("/arm") -> {
                    armed += popJson.decodeFromString(ArmReq.serializer(), req.body.toByteArray().decodeToString()).attempt
                    respond("""{"error":"bad_attempt","detail":"current attempt is ${armed.last() + 1}"}""", HttpStatusCode.BadRequest, jsonHdr)
                }
                req.method == HttpMethod.Get && req.url.encodedPath == "/v1/session/s" ->
                    respond(sessionViews.removeAt(0), HttpStatusCode.OK, jsonHdr)
                else -> respond("""{"error":"unexpected"}""", HttpStatusCode.NotFound, jsonHdr)
            }
        }
        val api = PopApi("http://h", key = { FakeKey() }, engine = engine)
        return PopRun(api, NoAudio(), FakeKey(), "s", 'A', clock = { ClockOffset(0, 5.0, 10) })
    }

    @Test fun badAttemptOnArmFollowsView() = runTest {
        val result = ""","result":{"session_id":"s","attempt":1,"verdict":"NOT_NEAR","reason":"timeout"}"""
        val views = mutableListOf(
            view("confirmed", 0),
            view("confirmed", 1, ""","last_failure":{"attempt":0,"reason":"glitch","by":"B"}"""),
            view("done", 1, result),
        )
        val armed = mutableListOf<Int>()
        val calls = mutableListOf<String>()
        val r = run(views, armed, calls).run()
        assertEquals(listOf(0, 1), armed)
        assertEquals("timeout", r.reason)
        assertEquals(0, calls.count { it.endsWith("/abort") || it.endsWith("/fail") }, "$calls")
    }

    @Test fun badAttemptAtSameAttemptStillThrows() = runTest {
        val views = mutableListOf(view("confirmed", 0), view("confirmed", 0))
        val e = assertFailsWith<PopHttpException> { run(views, mutableListOf(), mutableListOf()).run() }
        assertEquals("bad_attempt", e.code)
    }
}
