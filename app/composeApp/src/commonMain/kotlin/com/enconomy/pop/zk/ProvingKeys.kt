package com.enconomy.pop.zk

import com.enconomy.pop.sha256
import com.enconomy.pop.toHex
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay

/**
 * Prover artifacts (zkmobile/APP_SERVER_CONTRACT.md), served by the server at GET /v1/zk/keys/{file},
 * size + sha256 pinned here: the nargo artifact (ABI + ACIR), the BN254 CRS for 2^20 gates and the vk.
 * All public; a swapped file only makes proofs fail (the server / chain pins the vk).
 */
class KeySpec(val circuit: String, val sampleRate: Int, val sha256: String, val size: Long, val file: String = "$circuit.pk.zst") {
    val urlPath: String get() = "/v1/zk/keys/$file"
}

/** One Noir circuit and the files its prover needs. */
class CircuitSpec(val id: String, val sampleRate: Int, val artifact: KeySpec, val crs: KeySpec, val vk: KeySpec) {
    val files: List<KeySpec> get() = listOf(artifact, crs, vk)
    val bytes: Long get() = files.sumOf { it.size }
    /** Peak while proving: Pixel 6 1.6 GB, iPhone X 1.3 GB (zkmobile spike). */
    fun peakBytes(hardLimit: Boolean): Long = if (hardLimit) 1_350_000_000L else 1_700_000_000L
}

object ProvingKeys {
    val phoneJson = KeySpec("oaN_s48.json", 48000, "5499f99eed7aecfd6615ab470cfed7a3345e28954385005d8080b810aaf04f3a", 14_620_501, "oaN_s48.json")
    val crs = KeySpec("bn254_g1_2p20.dat", 0, "5d0ff516149e0c6644ab16567b914c9d02bf41f872c1129af8436b41d4d82c62", 67_108_864, "bn254_g1_2p20.dat")
    val vk = KeySpec("oaN_s48.vk", 48000, "769ac93112de4ec2f970d33233108d19124612b9b2ae54b8b531a23ecaa23f06", 1_888, "oaN_s48.vk")
    val s48 = CircuitSpec(WitnessInput.CIRCUIT_S48, 48000, phoneJson, crs, vk)
    val all = listOf(phoneJson, crs, vk)
    val circuits = listOf(s48)

    fun forRate(sr: Int): CircuitSpec? = circuits.firstOrNull { it.sampleRate == sr }
    fun forCircuit(c: String): CircuitSpec? = circuits.firstOrNull { it.id == c }
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
        ZkFiles.delete(path(k)); ZkFiles.delete(path(k) + ".part"); verified.remove(k.file)
    }

    /** Path of a verified key, downloading what is missing. [progress] (bytes, total). */
    suspend fun ensure(k: KeySpec, progress: (Long, Long) -> Unit = { _, _ -> }): String {
        val fin = path(k)
        if (k.file in verified && present(k)) return fin
        if (ZkFiles.size(fin) >= 0) {
            if (present(k) && hashOk(k, fin)) { verified += k.file; return fin }
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
                verified += k.file
                return fin
            }
            ZkFiles.delete(part)
            if (refetched) throw KeyException("hash_mismatch", "${k.file} does not match the pinned sha256")
            refetched = true
        }
    }

    private fun hashOk(k: KeySpec, p: String): Boolean = sha256(ZkFiles.read(p)).toHex() == k.sha256
}
