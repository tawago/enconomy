package com.enconomy.pop.zk

import com.enconomy.pop.PopApi
import com.enconomy.pop.sha256
import com.enconomy.pop.testTempDir
import com.enconomy.pop.toHex
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** Key download: Range resume, hash pin, refetch once, server ignoring Range, 404. */
class KeyCacheTest {
    private val data = ByteArray(300_000) { (it * 7 + it / 1000).toByte() }
    private val spec = KeySpec("oa2t_test", 48000, sha256(data).toHex(), data.size.toLong())

    /** Serves [body] at the key path; [cut] ends the first n responses early (dropped connection). */
    private class Server(var body: ByteArray, var honorRange: Boolean = true, var cut: Int = 0, var status404: Boolean = false) {
        val ranges = ArrayList<String?>()
        val engine = MockEngine { req ->
            ranges += req.headers[HttpHeaders.Range]
            if (status404) return@MockEngine respond("{\"error\":\"not_found\"}", HttpStatusCode.NotFound)
            val from = req.headers[HttpHeaders.Range]?.removePrefix("bytes=")?.removeSuffix("-")?.toInt()
            var slice = if (from != null && honorRange) body.copyOfRange(from, body.size) else body
            if (cut > 0) { cut--; slice = slice.copyOf(slice.size / 2) }
            if (from != null && honorRange) {
                respond(slice, HttpStatusCode.PartialContent, headersOf(HttpHeaders.ContentRange, "bytes $from-${body.size - 1}/${body.size}"))
            } else {
                respond(slice, HttpStatusCode.OK)
            }
        }
    }

    private fun cache(dir: String, s: Server): KeyCache {
        val api = PopApi("http://pop.test", engine = s.engine, clockSync = false)
        return KeyCache(dir, { p, from, a, b -> api.download(p, from, a, b) }, retries = 3, backoffMs = 1)
    }

    @Test
    fun downloadsResumesAndPins() = runTest {
        val dir = testTempDir()
        val s = Server(data, cut = 1)
        val c = cache(dir, s)
        var last = 0L
        val p = c.ensure(spec) { d, _ -> last = d }
        assertContentEquals(data, ZkFiles.read(p))
        assertEquals(data.size.toLong(), last)
        assertEquals(listOf(null, "bytes=150000-"), s.ranges)
        // cached: no request
        c.ensure(spec)
        assertEquals(2, s.ranges.size)
        // another process: hashes the file once, still no request
        cache(dir, s).ensure(spec)
        assertEquals(2, s.ranges.size)
    }

    @Test
    fun resumesFromPartAndRestartsWhenRangeIgnored() = runTest {
        val dir = testTempDir()
        ZkFiles.write("$dir/${spec.file}.part", data.copyOf(1000))
        val s = Server(data, honorRange = false)
        val p = cache(dir, s).ensure(spec)
        assertContentEquals(data, ZkFiles.read(p))
        assertEquals(listOf<String?>("bytes=1000-"), s.ranges)
    }

    @Test
    fun wrongBytesRefetchOnceThenFail() = runTest {
        val dir = testTempDir()
        val bad = data.copyOf().also { it[5] = (it[5] + 1).toByte() }
        val s = Server(bad)
        val e = assertFailsWith<KeyException> { cache(dir, s).ensure(spec) }
        assertEquals("hash_mismatch", e.reason)
        assertEquals(2, s.ranges.size)
        assertEquals(-1L, ZkFiles.size("$dir/${spec.file}"))
        assertEquals(-1L, ZkFiles.size("$dir/${spec.file}.part"))
        // a corrupt file at the final path (e.g. bad adb push) is replaced
        ZkFiles.write("$dir/${spec.file}", bad)
        s.body = data
        assertContentEquals(data, ZkFiles.read(cache(dir, s).ensure(spec)))
    }

    @Test
    fun notServed() = runTest {
        val e = assertFailsWith<KeyException> { cache(testTempDir(), Server(data, status404 = true)).ensure(spec) }
        assertEquals("not_served", e.reason)
    }

    @Test
    fun pinsMatchDocs() {
        assertEquals("5499f99eed7aecfd6615ab470cfed7a3345e28954385005d8080b810aaf04f3a", ProvingKeys.forRate(48000)!!.artifact.sha256)
        assertEquals(null, ProvingKeys.forRate(44100))
        assertEquals("/v1/zk/keys/oaN_s48.json", ProvingKeys.s48.artifact.urlPath)
    }
}
