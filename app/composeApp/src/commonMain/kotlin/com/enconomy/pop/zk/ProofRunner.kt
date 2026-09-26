package com.enconomy.pop.zk

import com.enconomy.pop.dsp.Popt2Code
import com.enconomy.pop.fromB64
import com.enconomy.pop.hexToBytes
import com.enconomy.pop.monoNanos
import com.enconomy.pop.popJson
import com.enconomy.pop.sha256
import com.enconomy.pop.toHex
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/** One v2 attempt this phone signed; kept in memory until the verdict (never persisted: holds the capture). */
class Popt2Evidence(
    val sessionId: String,
    val attempt: Int,
    val role: Char,
    val transcript: ByteArray,
    val sig: ByteArray,
    val capture: ShortArray,
    val tree: OaHash.RecTree2,
    val own: Popt2Code,
    val partner: Popt2Code,
    val t0Ms: Long,
    val provable: Boolean?,
)

sealed class ProofStatus {
    data class Skipped(val why: String) : ProofStatus()
    /** Key missing and the phone is on a metered network: wait for the user. */
    data class NeedKey(val circuit: String, val bytes: Long) : ProofStatus()
    data class Downloading(val done: Long, val total: Long) : ProofStatus()
    data class Step(val name: String) : ProofStatus()
    data class Done(val stats: ProofStats, val upload: String?) : ProofStatus()
    /** The server proved from our inputs ([ok] = verified). */
    data class Delegated(val note: String, val ok: Boolean) : ProofStatus()
    data class Failed(val step: String, val why: String) : ProofStatus()
}

class ProofStats(
    val circuit: String,
    val witnessMs: Long,
    val loadMs: Long,
    val checkMs: Long,
    val proveMs: Long,
    val proofBytes: Int,
    /** Max sampled process footprint while the key was open. */
    val peakBytes: Long,
    /** OS peak (Android VmHWM since reset, iOS lifetime ledger peak). */
    val osPeakBytes: Long?,
    val nativeHeapPeak: Long?,
    val totalRam: Long,
    val halfCommit: String,
    /** Prover's public vector == the one derived from the signed transcript (and the fixture's, on the bench). */
    val publicMatches: Boolean,
) {
    fun lines(): List<String> = listOfNotNull(
        "circuit $circuit",
        "input map ${ms(witnessMs)}, ACVM witness + prove ${ms(proveMs)}",
        "proof ${kb(proofBytes.toLong())}",
        "peak footprint ${mb(peakBytes)}" + (osPeakBytes?.let { ", OS peak ${mb(it)}" } ?: "") +
            (nativeHeapPeak?.let { ", native heap ${mb(it)}" } ?: ""),
        "device RAM ${mb(totalRam)}",
        "public inputs ${if (publicMatches) "match" else "DIFFER"}",
    )

    companion object {
        fun ms(v: Long) = if (v >= 10_000) "${v / 1000} s" else "${v / 100 / 10.0} s"
        fun kb(v: Long) = "${(v + 512) / 1024} KB"
        fun mb(v: Long) = "${(v + (1 shl 19)) shr 20} MB"
    }
}

/**
 * Proving pipeline shared by the post-verdict proof and the bench:
 * memory guard -> artifacts (download if needed) -> Noir input map (Kotlin, with the pre-checks) ->
 * native ACVM witness + UltraHonk prove -> public inputs compared with the expected ones. Native call on Dispatchers.Default.
 */
class ProofRunner(val keys: KeyCache) {
    class Out(val built: WitnessInput.Built, val proof: ByteArray, val publicInputs: ByteArray, val stats: ProofStats)

    /** Non-null = do not try locally: RAM clearly too small (or too little free on Android). */
    fun memoryProblem(c: CircuitSpec): String? {
        val m = DeviceMemory.info()
        val need = c.peakBytes(m.hardLimit)
        if (m.totalBytes in 1 until need * 3 / 2) {
            return "This phone has ${ProofStats.mb(m.totalBytes)} RAM; the prover needs about ${ProofStats.mb(need)}. Skipped."
        }
        val avail = m.availBytes
        if (avail != null && m.hardLimit && avail + m.usedBytes < need) {
            return "iOS lets this app use about ${ProofStats.mb(avail + m.usedBytes)}; the prover needs about ${ProofStats.mb(need)} " +
                "(needs the increased-memory-limit entitlement or a bigger phone). Skipped."
        }
        if (avail != null && !m.hardLimit && avail < need * 3 / 4) {
            return "Only ${ProofStats.mb(avail)} free now; the prover needs about ${ProofStats.mb(need)}. Close other apps and retry."
        }
        return null
    }

    fun missing(c: CircuitSpec): Long = c.files.filter { !keys.present(it) }.sumOf { it.size - keys.partial(it) }

    /**
     * [expectPublic] (bench): the public_inputs bytes the proof must carry.
     * Throws UnprovableException / KeyException / ProverException.
     */
    suspend fun run(
        src: ProofSource,
        allowDownload: Boolean,
        onStatus: (ProofStatus) -> Unit,
        force: Boolean = false,
        expectPublic: ByteArray? = null,
        prebuilt: WitnessInput.Built? = null,
    ): Out? {
        if (!ProverLib.available) { onStatus(ProofStatus.Skipped(ProverLib.loadError ?: "no native prover")); return null }
        val t = com.enconomy.pop.TranscriptCodec.decodeTranscript2(src.transcript)
        val c = ProvingKeys.forRate(t.sampleRate) ?: run {
            onStatus(ProofStatus.Skipped("no circuit for ${t.sampleRate} Hz (48 kHz only)")); return null
        }
        if (!force) memoryProblem(c)?.let { onStatus(ProofStatus.Skipped(it)); return null }
        val need = missing(c)
        if (need > 0 && !allowDownload) { onStatus(ProofStatus.NeedKey(c.id, need)); return null }

        val paths = c.files.map { f -> keys.ensure(f) { d, n -> onStatus(ProofStatus.Downloading(d, n)) } }
        onStatus(ProofStatus.Step("building witness input"))
        var t0 = monoNanos()
        val built = prebuilt ?: withContext(Dispatchers.Default) { WitnessInput.build(src) }
        val input = withContext(Dispatchers.Default) { built.json.encodeToByteArray() }
        val witnessMs = (monoNanos() - t0) / 1_000_000

        // one native prove at a time (~1.5 GB each): the bench and a live proof, or a cancelled prove still running
        if (nativeLock.isLocked) onStatus(ProofStatus.Step("waiting for the other proof to finish"))
        return nativeLock.withLock { coroutineScope {
            var peak = DeviceMemory.footprint()
            var heapPeak = DeviceMemory.nativeHeap()
            DeviceMemory.resetPeak()
            val sampler = launch(Dispatchers.Default) {
                while (isActive) {
                    peak = maxOf(peak, DeviceMemory.footprint())
                    DeviceMemory.nativeHeap()?.let { h -> heapPeak = maxOf(heapPeak ?: 0L, h) }
                    delay(50)
                }
            }
            try {
                withContext(Dispatchers.Default) {
                    onStatus(ProofStatus.Step("witness + proving (UltraHonk)"))
                    t0 = monoNanos()
                    val p = try {
                        ProverLib.prove(paths[0], input, paths[1], paths[2])
                    } catch (e: ProverException) {
                        if (e.code == "Witness") throw UnprovableException("witness", e.message ?: "ACVM execute failed")
                        throw e
                    }
                    val proveMs = (monoNanos() - t0) / 1_000_000
                    peak = maxOf(peak, DeviceMemory.footprint())
                    val matches = p.publicInputs.contentEquals(built.expectedPublic) &&
                        (expectPublic == null || p.publicInputs.contentEquals(expectPublic))
                    if (!matches) throw ProverException("Arg", "public inputs differ from the expected ones (${p.publicInputs.size / 32} values)")
                    Out(built, p.proof, p.publicInputs, ProofStats(
                        built.circuit, witnessMs, 0, 0, proveMs, p.proof.size, peak, DeviceMemory.peak(),
                        heapPeak, DeviceMemory.info().totalBytes, built.halfCommit.toDecimal(), matches,
                    ))
                }
            } finally {
                sampler.cancel()
            }
        } }
    }

    companion object {
        private val nativeLock = Mutex()
        /** A native prover call is running (possibly from a cancelled job). */
        val busy: Boolean get() = nativeLock.isLocked
    }
}

/** Bundled bench fixture (composeResources/files/zk/bench_*.json, commonTest/resources/zk/tools/gen_bench_noir.py). */
class BenchFixture(val name: String, val source: ProofSource, val inputSha: Map<String, String>, val publicInputs: ByteArray, val halfCommit: String) {
    companion object {
        val NAMES = listOf("180ca04b_48k_A", "180ca04b_48k_B")

        fun parse(text: String): BenchFixture {
            val o = popJson.parseToJsonElement(text).jsonObject
            fun s(k: String) = o[k]!!.jsonPrimitive.content
            val pcm = s("capture_b64").fromB64()
            val x = ShortArray(pcm.size / 2) { ((pcm[2 * it].toInt() and 0xff) or (pcm[2 * it + 1].toInt() shl 8)).toShort() }
            val e = o["expect"]!!.jsonObject
            val src = ProofSource(
                transcript = s("transcript_b64").fromB64(), sig = s("sig_b64").fromB64(), capture = x,
                own = Popt2Code(s("own_cI_b64").fromB64(), s("own_cQ_b64").fromB64()),
                partner = Popt2Code(s("partner_cI_b64").fromB64(), s("partner_cQ_b64").fromB64()),
                cred = Sbcred3(s("cred_b64").fromB64()), credSig = s("cred_sig_b64").fromB64(),
                issuerPub = s("issuer_pub").hexToBytes(), validAt = o["valid_at"]!!.jsonPrimitive.long,
                salt = s("salt_hex").hexToBytes(),
            )
            check(o["sample_rate"]!!.jsonPrimitive.int > 0)
            return BenchFixture(
                s("name"), src, e["input_sha256"]!!.jsonObject.mapValues { it.value.jsonPrimitive.content },
                e["public_inputs_hex"]!!.jsonPrimitive.content.hexToBytes(), e["half_commit"]!!.jsonPrimitive.content,
            )
        }
    }

    /** Input fields whose compact JSON differs from the team's Prover.toml (gen_inputs.py). */
    fun fieldMismatches(b: WitnessInput.Built): List<String> {
        val names = (inputSha.keys + b.fields.keys).sorted()
        return names.filter { n -> b.fields[n]?.let { sha256(it.toString().encodeToByteArray()).toHex() } != inputSha[n] }
    }
}

/** Parsed proof-upload reply for the status line. */
fun uploadSummary(body: String): String = runCatching {
    val o = popJson.parseToJsonElement(body) as JsonObject
    listOfNotNull(o["status"], o["verdict"], o["result"], o["accepted"]).firstOrNull()?.let { "server: $it".replace("\"", "") } ?: "uploaded"
}.getOrDefault("uploaded")

/** Status line for a rejected proof upload (server/pop/main.py proof route). */
fun proofUploadNote(e: com.enconomy.pop.PopHttpException): String = when {
    e.status == 409 && e.code == "already_submitted" -> "server: verified (already submitted)"
    e.status == 503 || e.code == "zk_unavailable" -> "server can't verify proofs now; kept on the phone"
    e.status == 404 || e.status == 405 -> "server takes no proofs; kept on the phone"
    else -> "upload rejected: ${e.code ?: e.status}; kept on the phone"
}
