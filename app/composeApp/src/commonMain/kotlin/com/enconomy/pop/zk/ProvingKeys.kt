package com.enconomy.pop.zk

import com.enconomy.pop.sha256
import com.enconomy.pop.toHex
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay

/**
 * Proving keys (docs/pop-prover.md): zstd-compressed, served by the server at
 * GET /v1/zk/keys/{circuit}.pk.zst, sha256 pinned here. The pk is public; a swapped one only makes proofs
 * fail (the server pins the vk). New trusted setup = new pins here and new vk pins on the server.
 */
class KeySpec(val circuit: String, val sampleRate: Int, val sha256: String, val size: Long) {
    val file: String get() = "$circuit.pk.zst"
    val urlPath: String get() = "/v1/zk/keys/$file"
    /** Rough peak while proving with this key (M2 measurement, port spec §5.5). */
    val peakBytes: Long get() = 1_950_000_000L
}

object ProvingKeys {
    val s48 = KeySpec("oa2t_s48", 48000, "49b6ed65e25fb25018cbc87beba5061f36aa9b24ddf3c47fb0a72ad2243bd045", 11_690_873)
    val s44 = KeySpec("oa2t_s44", 44100, "136ddb87868da3dea4aa3055ec18b634f54b3bf52fb25dda2a1273d93625f8d1", 11_273_564)
    val all = listOf(s48, s44)

    fun forRate(sr: Int): KeySpec? = all.firstOrNull { it.sampleRate == sr }
    fun forCircuit(c: String): KeySpec? = all.firstOrNull { it.circuit == c }
}

class KeyException(val reason: String, msg: String) : Exception("$reason: $msg")

/** Streaming GET with Range, see PopApi.download. */
typealias RangeGet = suspend (path: String, from: Long, onStart: suspend (Int, Long?) -> Unit, onChunk: suspend (ByteArray) -> Unit) -> Int

/**
 * Downloads and caches keys in [dir]: `<file>.part` + `Range: bytes=<n>-` on retry, sha256 on completion,
 * atomic rename. Hash mismatch: delete and fetch once more, then fail. A file already at the final path
 * (earlier download, or adb push / Xcode copy) is hashed once per process before use.
 */
class KeyCache(
    private val dir: String,
    private val get: RangeGet,
    private val retries: Int = 3,
    private val backoffMs: Long = 1000,
) {
    private val verified = HashSet<String>()

    fun path(k: KeySpec) = "$dir/${k.file}"

    /** Final file present with the pinned size (hash not yet checked this process). */
    fun present(k: KeySpec): Boolean = ZkFiles.size(path(k)) == k.size

    /** Bytes of a partial download, 0 when none. */
    fun partial(k: KeySpec): Long = maxOf(0L, ZkFiles.size(path(k) + ".part"))

    fun delete(k: KeySpec) {
        ZkFiles.delete(path(k)); ZkFiles.delete(path(k) + ".part"); verified.remove(k.circuit)
    }

    /** Path of a verified key, downloading what is missing. [progress] (bytes, total). */
    suspend fun ensure(k: KeySpec, progress: (Long, Long) -> Unit = { _, _ -> }): String {
        val fin = path(k)
        if (k.circuit in verified && present(k)) return fin
        if (ZkFiles.size(fin) >= 0) {
            if (present(k) && hashOk(k, fin)) { verified += k.circuit; return fin }
            ZkFiles.delete(fin)
        }
        val part = "$fin.part"
        var refetched = false
        var fails = 0
        while (true) {
            var have = maxOf(0L, ZkFiles.size(part))
            if (have > k.size) { ZkFiles.delete(part); have = 0 }
            if (have < k.size) {
                progress(have, k.size)
                val st = try {
                    get(k.urlPath, have, { st, _ ->
                        // server ignored the Range: start over
                        if (st == 200 && have > 0) { ZkFiles.delete(part); have = 0 }
                    }) { chunk ->
                        ZkFiles.append(part, chunk)
                        have += chunk.size
                        progress(have, k.size)
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Throwable) {
                    if (++fails > retries) throw KeyException("network", "key download failed: ${e.message}")
                    delay(backoffMs * fails)
                    continue
                }
                when (st) {
                    200, 206 -> {}
                    416 -> { ZkFiles.delete(part); if (++fails > retries) throw KeyException("http_416", "range refused"); continue }
                    404 -> throw KeyException("not_served", "server has no ${k.file}")
                    else -> {
                        if (st in 400..499 || ++fails > retries) throw KeyException("http_$st", "key download: HTTP $st")
                        delay(backoffMs * fails); continue
                    }
                }
                if (ZkFiles.size(part) < k.size) {
                    // connection dropped mid-body: resume
                    if (++fails > retries) throw KeyException("network", "key download incomplete (${ZkFiles.size(part)} of ${k.size})")
                    continue
                }
            }
            if (ZkFiles.size(part) == k.size && hashOk(k, part)) {
                if (!ZkFiles.rename(part, fin)) throw KeyException("io", "cannot move key into place")
                verified += k.circuit
                return fin
            }
            ZkFiles.delete(part)
            if (refetched) throw KeyException("hash_mismatch", "${k.file} does not match the pinned sha256")
            refetched = true
        }
    }

    private fun hashOk(k: KeySpec, p: String): Boolean = sha256(ZkFiles.read(p)).toHex() == k.sha256
}
