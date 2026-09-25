package com.enconomy.pop

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.abs
import kotlin.math.round
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Two in-process phones (software P-256 keys, fake air instead of mic/speaker) run PopRun against a
 * live server: POP_LIVE_URL=http://127.0.0.1:8000, server started with POP_ALLOW_UNATTESTED=1.
 * Skipped when POP_LIVE_URL is unset. Covers arm/t0/commit-then-reveal/transcript/verdict/retry
 * with the real Kotlin DSP and the real server checks.
 */
class LiveServerRunTest {
    private val url = System.getenv("POP_LIVE_URL")?.takeIf { it.isNotBlank() }

    @Test fun nearAt30cm() = live { a, b ->
        val (ra, rb) = pair(a, b, Air(30.0))
        assertEquals("NEAR", ra.verdict, "$ra")
        assertEquals(ra, rb)
        assertTrue(abs(ra.flight_cm!! - 30.0) < 3.0, "flight ${ra.flight_cm}")
    }

    @Test fun farIsFinal() = live { a, b ->
        val (ra, _) = pair(a, b, Air(150.0))
        assertEquals("NOT_NEAR", ra.verdict)
        assertEquals("too_far", ra.reason)
        assertEquals(1, ra.attempts.size)
    }

    @Test fun glitchRetriesOnce() = live { a, b ->
        val (ra, rb) = pair(a, b, Air(10.0, glitchB = setOf(0)))
        assertEquals("NEAR", ra.verdict, "$ra")
        assertEquals(1, ra.attempt)
        assertEquals(2, ra.attempts.size)
        assertEquals("\"glitch\"", ra.attempts[0]["reason"].toString())
        assertEquals(ra, rb)
    }

    private fun live(body: suspend (JvmKey, JvmKey) -> Unit) {
        if (url == null) { println("POP_LIVE_URL unset, skipping"); return }
        runBlocking {
            val a = JvmKey(); val b = JvmKey()
            enroll(a, "host"); enroll(b, "guest")
            withTimeout(90_000) { body(a, b) }
        }
    }

    private suspend fun enroll(k: JvmKey, name: String) {
        val api = PopApi(url!!)
        try {
            val n = api.enrollNonce().nonce
            api.enroll(EnrollReq(n, k.deviceId, k.pubkey.toHex(), name, "jvm", "software", null))
        } finally { api.close() }
    }

    private suspend fun pair(a: JvmKey, b: JvmKey, air: Air): Pair<ResultRecord, ResultRecord> {
        val apiA = PopApi(url!!, key = { a })
        val apiB = PopApi(url, key = { b })
        try {
            val inv = apiA.createSession()
            apiB.join(inv.session_id, inv.join_token)
            apiA.confirm(inv.session_id); apiB.confirm(inv.session_id)
            val phases = ConcurrentHashMap<Char, MutableList<RunPhase>>()
            suspend fun run(api: PopApi, key: JvmKey, role: Char) = PopRun(api, FakeEngine(air, role), key, inv.session_id, role,
                onStatus = { p, _, _ -> phases.getOrPut(role) { mutableListOf() }.add(p) }).run()
            return kotlinx.coroutines.coroutineScope {
                val ra = async(Dispatchers.Default) { run(apiA, a, 'A') }
                val rb = async(Dispatchers.Default) { run(apiB, b, 'B') }
                val out = ra.await() to rb.await()
                println("phases A=${phases['A']} B=${phases['B']}")
                println("result ${out.first}")
                out
            }
        } finally { apiA.close(); apiB.close() }
    }
}

class JvmKey : DeviceKey {
    private val kp = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
    override val pubkey: ByteArray = (kp.public as ECPublicKey).w.let { byteArrayOf(4) + fixed(it.affineX.toByteArray()) + fixed(it.affineY.toByteArray()) }
    override val securityLevel = "software"
    override fun sign(message: ByteArray): ByteArray =
        derToRawRs(Signature.getInstance("SHA256withECDSA").apply { initSign(kp.private); update(message) }.sign())

    private fun fixed(b: ByteArray): ByteArray = if (b.size >= 32) b.copyOfRange(b.size - 32, b.size) else ByteArray(32 - b.size) + b
}

/** Both phones' sound in one room: emitter onset (nanoTime) + delay by distance, into each capture. */
class Air(val distanceCm: Double, val glitchB: Set<Int> = emptySet()) {
    val emitted = ConcurrentHashMap<String, Pair<Long, FloatArray>>()
    val attempts = ConcurrentHashMap<Char, Int>()
}

class FakeEngine(private val air: Air, private val role: Char, private val sr: Int = 48000) : AudioEngine {
    private var play = FloatArray(0)
    override fun preflight() = AudioPreflight(sr, 15, 15, null, true, true, 10.0, emptyList(), emptyList())
    override fun setMediaVolume(frac: Double) {}
    override fun prepare(sr: Int, play: FloatArray) { this.play = play }
    override fun release() {}

    override suspend fun run(plan: RunPlan): Capture {
        val attempt = air.attempts.merge(role, 1, Int::plus)!! - 1
        val onset = plan.t0Ns + secToNs(plan.playOffsetS)
        air.emitted["$role$attempt"] = onset to play
        val other = if (role == 'A') 'B' else 'A'
        while (air.emitted["$other$attempt"] == null) delay(10)
        while (System.nanoTime() < plan.stopNs) delay(10)
        val n = plan.captureFrames
        val c0 = plan.captureStartNs
        val rnd = Random(role.code * 31 + attempt)
        val x = DoubleArray(n) { rnd.nextDouble(-60.0, 60.0) }
        fun add(atNs: Long, pcm: FloatArray, extraFrames: Double) {
            val f = round((atNs - c0) * sr / 1e9 + extraFrames).toInt()
            for (i in pcm.indices) if (f + i in 0 until n) x[f + i] += 0.3 * 32767 * pcm[i]
        }
        add(onset, play, 2.0) // own speaker -> own mic
        val (po, pp) = air.emitted["$other$attempt"]!!
        add(po, pp, air.distanceCm / PopConstants.SPEED_OF_SOUND_CM_S * sr)
        val pcm = ShortArray(n) { x[it].coerceIn(-32768.0, 32767.0).toInt().toShort() }
        if (role == 'B' && attempt in air.glitchB) pcm.fill(0, sr, sr + sr / 50) // 20 ms dropped block at 1.0 s
        return Capture(pcm, sr, c0, AudioTiming.primerFrames(sr).toLong(), onset, "audiotimestamp", "audiotimestamp",
            10.0, "fake", emptyList(), 0.0, 0.0, n.toLong(), 0, true)
    }
}
