package com.enconomy.pop

import com.enconomy.pop.chain.Allowlist
import com.enconomy.pop.chain.ContextGate
import com.enconomy.pop.chain.SafeTx
import com.enconomy.pop.res.Res
import com.enconomy.pop.zk.BenchFixture
import com.enconomy.pop.zk.CredentialException
import com.enconomy.pop.zk.DeviceMemory
import com.enconomy.pop.zk.KeyCache
import com.enconomy.pop.zk.KeyException
import com.enconomy.pop.zk.KeySpec
import com.enconomy.pop.zk.Popt2Evidence
import com.enconomy.pop.zk.ProofRunner
import com.enconomy.pop.zk.ProofSource
import com.enconomy.pop.zk.ProofStats
import com.enconomy.pop.zk.ProofStatus
import com.enconomy.pop.zk.ProverException
import com.enconomy.pop.zk.ProverLib
import com.enconomy.pop.zk.ProvingKeys
import com.enconomy.pop.zk.UnprovableException
import com.enconomy.pop.zk.WitnessInput
import com.enconomy.pop.zk.ZkFiles
import com.enconomy.pop.zk.acceptCredential
import com.enconomy.pop.zk.networkIsMetered
import com.enconomy.pop.zk.toDecimal
import com.enconomy.pop.zk.proofUploadNote
import com.enconomy.pop.zk.uploadSummary
import io.ktor.client.network.sockets.SocketTimeoutException
import io.ktor.client.plugins.HttpRequestTimeoutException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.plus
import kotlin.concurrent.atomics.AtomicReference
import kotlin.concurrent.atomics.ExperimentalAtomicApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.jetbrains.compose.resources.ExperimentalResourceApi

/** Build-time server URL (-Ppop.serverUrl / POP_SERVER_URL, see app/README.md). A saved Prefs value wins. */
val DEFAULT_BASE_URL: String = platformDefaultBaseUrl(PopBuildConfig.SERVER_URL)

/** Prefs key of the iOS audio session mode ("measurement" | "default" | "videoRecording"); Android uses "audio.backend". */
const val AUDIO_MODE_PREF = "audio.mode"

/** iOS session mode when Prefs has none: videoRecording hears itself ~35 dB over the floor (measurement ~18 dB). */
const val DEFAULT_AUDIO_MODE = "videoRecording"

enum class Screen { Enroll, Home, Safe, Host, Join, Confirm, Run, Result, Bench, AudioCheck }

/** Safe spend form: the Safe this phone co-owns, the Safe backend, one transfer. Prefs "safe.*". */
data class SafeForm(
    val backend: String = DEFAULT_SAFE_BACKEND,
    val safe: String = "",
    val to: String = "",
    /** "" = ETH, else the address of a token in [Allowlist.TOKENS]. */
    val token: String = "",
    val amount: String = "",
    /** Safe nonce, decimal; filled from the chain (eth_call nonce()), editable. */
    val nonce: String = "",
    val rpc: String = DEFAULT_SEPOLIA_RPC,
    val note: String? = null,
)

private const val CAL_CAPTURE_TRIES = 3

const val DEFAULT_SEPOLIA_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
/** The host Mac from the Android emulator, as the core's default. Real phones set this on the Safe screen. */
const val DEFAULT_SAFE_BACKEND = "http://10.0.2.2:8200"
/** "<ctx_hash> <session_id>" of a NEAR not accepted yet by the Safe backend: survives an app restart. */
private const val SAFE_PENDING = "safe.pending"
private const val DELIVERY_RETRY_MS = 3_000L
private const val DELIVERY_MAX_MS = 20 * 60_000L
private const val RELAY_POLL_MS = 2_000L
private const val RELAY_MAX_MS = 360_000L

/** Safe spend progress: owner sig, presence delivery, then the relay status from the Safe backend. */
data class SafeStatus(
    val ownerSig: String? = null,
    /** What became of the presence record: sending / waiting / accepted. */
    val delivery: String? = null,
    /** The backend said no: the text to show. Final. */
    val refused: String? = null,
    /** pending / success / reverted / skipped / error, from GET /v1/spends/{ctx_hash}/relay. */
    val relay: String? = null,
    val relayText: String? = null,
    val txLink: String? = null,
    val txHash: String? = null,
)

data class Enrollment(
    val deviceId: String,
    val serverUrl: String,
    val displayName: String,
    val attested: Boolean,
    val securityLevel: String,
    /** SBcred3 expiry (unix s), null = no credential (v1 server, or it was rejected). */
    val credExpiry: Long? = null,
    /** Enrollment calibration µs as last accepted by the server, null = none. */
    val calUs: Long? = null,
)

data class UiState(
    val baseUrl: String = DEFAULT_BASE_URL,
    val screen: Screen = Screen.Enroll,
    val busy: Boolean = false,
    val status: String = "",
    val error: String? = null,
    val displayName: String = "",
    val enrollment: Enrollment? = null,
    val invite: CreateSessionResp? = null,
    val session: SessionView? = null,
    val info: String? = null,
    /** null = not checked yet; true = /v1/config matches PopConstants (§1). */
    val configOk: Boolean? = null,
    /** Guest: invite decoded from NFC / QR (§3.2). */
    val joinInvite: Invite? = null,
    val role: String? = null,
    val confirmSent: Boolean = false,
    // ---- run (§9.2 Arming..Done) ----
    val runPhase: RunPhase? = null,
    val runAttempt: Int = 0,
    /** Retry reason text or what we wait on. */
    val runNote: String? = null,
    /** /v1/config "chain".chain_id. */
    val serverChainId: Long? = null,
    val safeForm: SafeForm = SafeForm(),
    /** This session's spend, past the gate on this phone. null = no spend (or a session without a context). */
    val spend: ContextGate.Spend? = null,
    /** Safe spend progress; stays after Done so a delivery in the background stays visible. */
    val safe: SafeStatus? = null,
    /** Pre-flight / clock problem; user fixes it and taps Start. */
    val runBlocked: String? = null,
    val preflight: AudioPreflight? = null,
    val result: ResultRecord? = null,
    /** Unexpected error detail shown with an aborted result. */
    val resultDetail: String? = null,
    val uploadRecordings: Boolean = true,
    /** Server offers POPT v2 with the app's constants (null = not checked yet). */
    val popt2Available: Boolean? = null,
    /** User switch (Prefs "popt"): v2 when available, else v1. */
    val popt2On: Boolean = true,
    /** Option A proof of our half after a NEAR verdict (null = none for this result). */
    val proof: ProofStatus? = null,
    /** The live proof job has not finished (a cancelled native prove runs to the end). */
    val proofBusy: Boolean = false,
    // ---- prover bench ----
    val benchStatus: ProofStatus? = null,
    val benchLog: List<String> = emptyList(),
    /** Per circuit: "present" / "partial n bytes" / "missing". */
    /** Prover files (circuit, CRS, vk) together: downloaded / missing / partly downloaded. */
    val keyState: String = "?",
    // ---- audio check ----
    val audioCheck: AudioCheckResult? = null,
    val audioCheckRunning: Boolean = false,
    /** Route before the check (or after the last one). */
    val audioRoute: AudioRoute? = null,
    val audioModes: List<String> = emptyList(),
    /** Prefs "audio.mode" (iOS session mode) or "audio.backend" (Android), also used for runs. */
    val audioMode: String = "",
    val audioModeTitle: String = "Session mode",
    val audioModeNote: String = "",
    /** Audio check only; runs always force the speaker. */
    val forceSpeaker: Boolean = true,
    /** Mic input presets (key, label), empty = none to pick (iOS). Prefs "audio.input", also used for runs. */
    val audioInputs: List<Pair<String, String>> = emptyList(),
    val audioInput: String = "",
    /** /v1/config "tune_db" (null = not seen). */
    val serverTuneDb: Double? = null,
    /** Audio check tune boost picked on screen (null = follow the server's tune_db, else 0). */
    val audioTuneDb: Double? = null,
) {
    val tuneDb: Double get() = audioTuneDb ?: serverTuneDb ?: 0.0
}

/**
 * App shell state. Enrollment is keyed on the device key only; a server that does not
 * know the device rejects signed calls (unknown_device) and the user re-enrolls.
 * Host/Join need a matching /v1/config (§1), checked at startup and on ping.
 * Pairing (§3): Host -> Inviting (QR + HCE), Join -> Scanning (NFC reader + camera),
 * both -> Confirm -> Run (PopRun: arm .. result, one server-driven retry) -> Result.
 */
/** Session states before both confirms. */
private val PRE_CONFIRM = setOf("created", "joined")

class PopController(
    private val keystore: DeviceKeystore,
    scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Main),
    engineFactory: () -> AudioEngine = ::createAudioEngine,
    holderFactory: () -> HolderStore = { HolderStore(createSecretStore(), PrefsKeyValue) },
) {
    /**
     * An uncaught throw in a launch would end the process on Kotlin/Native: every coroutine of the
     * controller lands here instead and shows up as an error on screen.
     */
    private val crashGuard = CoroutineExceptionHandler { _, e ->
        if (e is CancellationException) return@CoroutineExceptionHandler
        println("PopController: uncaught ${e::class.simpleName}: ${e.message}\n${e.stackTraceToString()}")
        _state.update { it.copy(busy = false, error = "${e::class.simpleName}: ${e.message}") }
    }
    private val scope: CoroutineScope = scope + crashGuard
    /** Open PopApi clients, so a return to the foreground can drop their clock offsets. */
    @OptIn(ExperimentalAtomicApi::class)
    private val liveApis = AtomicReference<Set<PopApi>>(emptySet())
    private val engine: AudioEngine by lazy(engineFactory)
    private val holder: HolderStore by lazy(holderFactory)
    private val _state = MutableStateFlow(initial())
    val state: StateFlow<UiState> = _state
    private var job: Job? = null
    private var safeJob: Job? = null
    private var popt2: Popt2Config? = null
    private var proofJob: Job? = null
    private var benchJob: Job? = null
    /** Evidence + verdict of the last NEAR v2 run, kept for "prove now" / retry. */
    private var pendingProof: Pair<Popt2Evidence, ResultRecord>? = null
    private val keyCache: KeyCache by lazy {
        KeyCache(ZkFiles.dir(), { path, from, onStart, onChunk ->
            val api = api()
            try { api.download(path, from, onStart, onChunk) } finally { api.close() }
        })
    }
    private val prover: ProofRunner by lazy { ProofRunner(keyCache) }

    init {
        checkConfig()
        resumeSafeDelivery()
    }

    private fun initial(): UiState {
        val url = Prefs.get("baseUrl") ?: DEFAULT_BASE_URL
        val name = Prefs.get("displayName") ?: deviceModel().take(32)
        val e = storedEnrollment()
        return UiState(baseUrl = url, displayName = name, enrollment = e, screen = if (e != null) Screen.Home else Screen.Enroll,
            popt2On = Prefs.get("popt") != "1", audioMode = Prefs.get(AUDIO_MODE_PREF) ?: "", safeForm = loadSafeForm())
    }

    private fun storedEnrollment(): Enrollment? {
        val key = keystore.load() ?: return null
        val id = Prefs.get("enroll.deviceId") ?: return null
        if (id != key.deviceId) return null
        return Enrollment(
            id, Prefs.get("enroll.url") ?: "", Prefs.get("enroll.name") ?: "", Prefs.get("enroll.attested") == "1", key.securityLevel,
            holder.credential(key.pubkey)?.expiry, Calibration.load()?.cal_us,
        )
    }

    @OptIn(ExperimentalAtomicApi::class)
    fun api(): PopApi = PopApi(state.value.baseUrl, key = { keystore.load() }, onClose = { a -> liveApis.update { it - a } })
        .also { a -> liveApis.update { it + a } }

    @OptIn(ExperimentalAtomicApi::class)
    private inline fun <T> AtomicReference<T>.update(f: (T) -> T) {
        while (true) {
            val cur = load()
            if (compareAndSet(cur, f(cur))) return
        }
    }

    /**
     * App back in the foreground (iOS scene active, Android onResume): the phone may have slept.
     * Drop every client's server offset (next signed call syncs /v1/time first).
     */
    @OptIn(ExperimentalAtomicApi::class)
    fun onForeground() {
        liveApis.load().forEach { it.invalidateClock() }
    }

    fun setBaseUrl(url: String) {
        Prefs.set("baseUrl", url)
        _state.update { it.copy(baseUrl = url, configOk = null) }
    }

    /** Forget the saved URL, back to the build default. */
    fun resetBaseUrl() {
        Prefs.set("baseUrl", null)
        _state.update { it.copy(baseUrl = DEFAULT_BASE_URL, configOk = null) }
    }

    /** POPT v2 on/off (v1 when off or when the server has no v2). */
    fun setPopt2(on: Boolean) {
        Prefs.set("popt", if (on) "2" else "1")
        _state.update { it.copy(popt2On = on) }
    }

    fun setDisplayName(n: String) {
        val v = n.take(32)
        Prefs.set("displayName", v)
        _state.update { it.copy(displayName = v) }
    }

    fun go(s: Screen) {
        if (s != Screen.Host) job?.cancel()
        if (s != Screen.Host) InviteBeacon.publish(null)
        _state.update { it.copy(screen = s, error = null, status = "") }
    }

    fun cancel() { job?.cancel() }

    private fun run(label: String, block: suspend (PopApi) -> Unit) {
        if (state.value.busy) return
        val api = api()
        _state.update { it.copy(busy = true, status = label, error = null) }
        job = scope.launch {
            try {
                block(api)
            } catch (e: CancellationException) {
                _state.update { it.copy(status = "cancelled") }
                throw e
            } catch (e: PopHttpException) {
                _state.update { it.copy(error = e.hint ?: e.code ?: "http_${e.status}", status = e.message ?: "") }
                // this server never saw our key: offer enroll, keep the key until the user re-enrolls
                if (e.code == "auth_unknown_device") _state.update { it.copy(screen = Screen.Enroll) }
            } catch (e: Throwable) {
                _state.update { it.copy(error = "${e::class.simpleName}: ${e.message}") }
            } finally {
                api.close()
                _state.update { it.copy(busy = false) }
            }
        }
    }

    /**
     * §2.2: nonce -> key with attestation challenge -> POST /v1/enroll.
     * Server with an issuer in /v1/config: also send holder_commit, check and keep the SBcred3.
     */
    fun enroll(calibrate: Boolean = true) = run("enrolling") { api ->
        val name = state.value.displayName.trim()
        require(name.length in 1..32) { "display name 1..32 chars" }
        // Calibration first (no key yet); a rejected one enrolls without (cal 0 = the old self check) and says so.
        var calErr: String? = null
        val cal = if (!calibrate) null else try {
            measureCalibration()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            calErr = "Calibration skipped (${e.message}); use Recalibrate"
            null
        }
        _state.update { it.copy(status = "enrolling") }
        val issuer = issuerPubkeyOf(api.config())
        holder.clearCredential()
        val hold = if (issuer != null) withContext(Dispatchers.Default) { holder.commit().toBytes() } else null
        val nonce = api.enrollNonce().nonce
        _state.update { it.copy(status = "generating key") }
        val gen = withContext(Dispatchers.Default) { keystore.generate(nonce.hexToBytes()) }
        val k = gen.key
        _state.update { it.copy(status = "enrolling ${k.deviceId.take(8)} (${k.securityLevel})") }
        val resp = api.enroll(
            EnrollReq(
                nonce = nonce,
                device_id = k.deviceId,
                pubkey = k.pubkey.toHex(),
                display_name = name,
                model = deviceModel(),
                security_level = k.securityLevel,
                chain = gen.chain?.map { it.toB64() },
                platform = keystore.platform,
                key_kind = if (keystore.platform == "ios") k.securityLevel else null,
                app_attest = gen.appAttest?.let { AppAttestReq(it.keyId, it.attestation.toB64()) },
                holder_commit = hold?.toHex(),
                calibration = cal,
                cal_sig_b64 = cal?.let { c -> withContext(Dispatchers.Default) { k.sign(Calibration.message(nonce, c)) }.toB64() },
            ),
        )
        check(resp.device_id == k.deviceId) { "server device_id ${resp.device_id} != ${k.deviceId}" }
        // enrolled either way; a bad credential only leaves us without one
        val cred = resp.credential
        val credErr = when {
            issuer == null || hold == null -> null
            cred == null -> "server issued no credential"
            else -> try {
                holder.saveCredential(
                    acceptCredential(cred.format, cred.cred_b64, cred.sig_b64, cred.expiry, cred.issuer_pubkey, issuer, k.pubkey, hold),
                )
                null
            } catch (e: CredentialException) {
                "credential rejected: ${e.message}"
            }
        }
        val url = state.value.baseUrl
        Prefs.set("enroll.deviceId", k.deviceId)
        Prefs.set("enroll.url", url)
        Prefs.set("enroll.name", name)
        Prefs.set("enroll.attested", if (resp.attested) "1" else "0")
        val calOk = cal != null && resp.calibration?.cal_us == cal.cal_us
        Calibration.save(if (calOk) cal else null)
        if (cal != null && !calOk) calErr = "server kept no calibration; use Recalibrate"
        val e = Enrollment(k.deviceId, url, name, resp.attested, k.securityLevel, holder.credential(k.pubkey)?.expiry,
            if (calOk) cal!!.cal_us else null)
        _state.update { it.copy(enrollment = e, screen = Screen.Home, status = "enrolled", error = listOfNotNull(credErr, calErr).joinToString("; ").ifEmpty { null }) }
    }

    fun forgetKey() {
        job?.cancel()
        keystore.delete()
        holder.clearCredential()
        Calibration.save(null)
        Prefs.set("enroll.deviceId", null)
        Prefs.set(SAFE_PENDING, null)
        _state.update { it.copy(enrollment = null, screen = Screen.Enroll) }
    }

    /** Server sanity: /v1/time + /v1/config (also re-runs the §1 constants check). */
    fun ping() = run("ping") { api ->
        val t0 = unixMs()
        val t = api.time()
        val rtt = unixMs() - t0
        val cfg = api.config()
        val ok = applyConfig(cfg)
        _state.update { it.copy(info = "rtt ${rtt} ms, server_ms ${t.server_ms}\n$cfg", status = if (ok) "ok" else "config mismatch") }
    }

    /** Startup §1 check; silent on network errors (configOk stays null, ping retries). */
    private fun checkConfig() {
        val api = api()
        scope.launch {
            try {
                applyConfig(api.config())
            } catch (e: CancellationException) {
                throw e
            } catch (_: Throwable) {
            } finally {
                api.close()
            }
        }
    }

    private fun applyConfig(cfg: JsonObject): Boolean {
        val bad = PopConstants.mismatches(cfg)
        val up = (cfg["upload_recordings"] as? kotlinx.serialization.json.JsonPrimitive)?.content != "false"
        val v2 = Popt2Config.from(cfg)
        popt2 = v2
        val tune = (cfg["tune_db"] as? kotlinx.serialization.json.JsonPrimitive)?.content?.toDoubleOrNull()
        val chainId = ((cfg["chain"] as? JsonObject)?.get("chain_id") as? kotlinx.serialization.json.JsonPrimitive)?.content?.toLongOrNull()
        _state.update {
            it.copy(uploadRecordings = up, serverChainId = chainId ?: it.serverChainId, serverTuneDb = tune ?: it.serverTuneDb, configOk = bad.isEmpty(), popt2Available = v2 != null,
                error = if (bad.isEmpty()) it.error else "config_mismatch: ${bad.joinToString()}")
        }
        return bad.isEmpty()
    }

    /** §1: fetch /v1/config if not yet checked; refuse on mismatch. */
    private suspend fun requireConfig(api: PopApi) {
        if (state.value.configOk != true) applyConfig(api.config())
        check(state.value.configOk == true) { "server constants differ from app (§6.1); refusing to run" }
    }

    fun join() {
        run("checking server") { api ->
            requireConfig(api)
            _state.update { it.copy(screen = Screen.Join, status = "") }
        }
    }

    /**
     * Host: POST /v1/session, publish the invite (QR + HCE), long-poll until a guest joins.
     * Token lives 120 s; an expired, unjoined session is replaced by a fresh one.
     */
    fun host() = startHost(null)

    /** [prepare] runs first and gives the session's context. A refusal there goes back to the Safe screen. */
    private fun startHost(prepare: (suspend () -> JsonObject)?) {
        go(Screen.Host)
        _state.update { it.copy(invite = null, session = null, role = "A", confirmSent = false, spend = null) }
        run("creating session") { api ->
            requireConfig(api)
            val me = keystore.load() ?: error("not enrolled")
            val context = try {
                prepare?.invoke()
            } catch (e: SpendRefused) {
                _state.update { it.copy(error = e.refused.code, status = ContextGate.text(e.refused), screen = Screen.Safe) }
                return@run
            }
            try {
                while (true) {
                    val inv = api.createSession(context)
                    val bytes = inviteBytes(inv, me.pubkey)
                    InviteBeacon.publish(bytes)
                    _state.update { it.copy(invite = inv.copy(invite_b64url = bytes.toB64Url()), session = null, status = "waiting for guest") }
                    val v = pollUntil(api, inv.session_id, deadlineMs = inv.expires_at_ms) { it.partner != null || it.state == "aborted" }
                    if (v?.partner != null) {
                        InviteBeacon.publish(null)
                        _state.update { it.copy(session = v, screen = Screen.Confirm, status = "guest joined") }
                        return@run
                    }
                    _state.update { it.copy(status = "invite expired, new session") }
                }
            } finally {
                InviteBeacon.publish(null)
            }
        }
    }

    /** Server bytes when present (§9 invite_b64url), else built locally from the create response. */
    private fun inviteBytes(inv: CreateSessionResp, hostPub: ByteArray): ByteArray {
        val local = Invite(inv.session_id, inv.join_token, inv.expires_at_ms / 1000, Invite.keyHint(hostPub))
        val srv = inv.invite_b64url?.let { runCatching { Invite.decode(it.fromB64Url()) }.getOrNull() } ?: return local.encode()
        check(srv.sessionId == inv.session_id && srv.joinToken == inv.join_token) { "server invite does not match session" }
        check(srv.hostHint.contentEquals(local.hostHint)) { "server invite key hint is not ours" }
        return srv.encode()
    }

    /** Long-poll the view until [done] or [deadlineMs] (unix ms). null = deadline hit first. */
    private suspend fun pollUntil(api: PopApi, id: String, deadlineMs: Long = Long.MAX_VALUE, done: (SessionView) -> Boolean): SessionView? {
        var seq: Long? = null
        var misses = 0
        while (true) {
            val left = deadlineMs - unixMs()
            if (left <= 0) return null
            val v = try {
                api.session(id, after = seq, timeoutS = (left / 1000).coerceIn(1, 25).toInt())
            } catch (e: HttpRequestTimeoutException) {
                if (++misses > 3) throw e
                delay(500); continue
            } catch (e: SocketTimeoutException) {
                if (++misses > 3) throw e
                delay(500); continue
            }
            misses = 0
            seq = v.seq
            _state.update { it.copy(session = v, status = "state ${v.state}") }
            if (done(v)) return v
            if (v.state == "aborted" || v.state == "done") return v
        }
    }

    // ---- guest (§3.3) ----

    /** QR text from the scanner. Non-pop codes are ignored silently. */
    fun onQrText(text: String) {
        if (!text.trim().startsWith(Invite.QR_PREFIX, ignoreCase = true)) return
        acceptInvite { Invite.parseValid(text, unixMs()) }
    }

    /** 49 bytes from the NFC SELECT response. */
    fun onNfcInvite(bytes: ByteArray) = acceptInvite { Invite.decodeValid(bytes, unixMs()) }

    fun onNfcError(code: String) {
        if (state.value.screen == Screen.Join && !state.value.busy) _state.update { it.copy(status = "nfc: $code") }
    }

    private fun acceptInvite(parse: () -> Invite) {
        val s = state.value
        if (s.screen != Screen.Join || s.busy) return
        val inv = try {
            parse()
        } catch (e: InviteException) {
            _state.update { it.copy(error = e.code, status = e.message ?: "") }
            return
        }
        _state.update { it.copy(joinInvite = inv, role = "B", confirmSent = false, session = null, spend = null) }
        run("joining ${inv.sessionId.take(8)}") { api ->
            var v = api.join(inv.sessionId, inv.joinToken)
            _state.update { it.copy(session = v) }
            if (v.partner?.pubkey == null) {
                v = pollUntil(api, inv.sessionId, deadlineMs = unixMs() + 10_000) { it.partner?.pubkey != null }
                    ?: error("host not visible after join")
            }
            val pk = v.partner?.pubkey ?: error("no partner pubkey")
            if (!inv.matchesHost(pk)) {
                runCatching { api.abort(inv.sessionId) }
                _state.update { it.copy(error = "partner_mismatch", status = "Invite does not match this partner.") }
                return@run
            }
            // a session with a context is a spend: this phone checks the transaction before Confirm
            val ctx = v.context
            if (ctx != null) {
                val g = guestGate(ctx)
                if (g is ContextGate.Result.Refused) {
                    refuse(api, inv.sessionId, g)
                    return@run
                }
                _state.update { it.copy(spend = (g as ContextGate.Result.Ok).spend) }
            }
            _state.update { it.copy(session = v, screen = Screen.Confirm, status = "joined") }
        }
    }

    // ---- Safe spend (examples/safe/README.md) ----

    private class SpendRefused(val refused: ContextGate.Result.Refused) : Exception()

    private fun chainId(): Long = state.value.serverChainId ?: SafeTx.CHAIN_SEPOLIA

    private suspend fun <T> withBackend(f: suspend (SafeBackend) -> T): T {
        val b = SafeBackend(state.value.safeForm.backend)
        try { return f(b) } finally { b.close() }
    }

    private fun loadSafeForm() = SafeForm(
        backend = Prefs.get("safe.backend") ?: DEFAULT_SAFE_BACKEND,
        safe = Prefs.get("safe.address") ?: "", to = Prefs.get("safe.to") ?: "", token = Prefs.get("safe.token") ?: "",
        amount = Prefs.get("safe.amount") ?: "0.001", rpc = Prefs.get("safe.rpc") ?: DEFAULT_SEPOLIA_RPC,
    )

    fun openSafe() {
        _state.update { it.copy(safeForm = loadSafeForm().copy(nonce = it.safeForm.nonce), screen = Screen.Safe, error = null, status = "") }
        refreshSafeNonce()
    }

    fun setSafeForm(f: SafeForm) {
        val g = f.copy(backend = f.backend.trim(), safe = f.safe.trim().lowercase(), to = f.to.trim().lowercase())
        Prefs.set("safe.backend", g.backend.takeIf { it != DEFAULT_SAFE_BACKEND && it.isNotBlank() })
        Prefs.set("safe.address", g.safe.ifEmpty { null })
        Prefs.set("safe.to", g.to.ifEmpty { null })
        Prefs.set("safe.token", g.token.ifEmpty { null })
        Prefs.set("safe.amount", g.amount.ifEmpty { null })
        Prefs.set("safe.rpc", g.rpc.takeIf { it != DEFAULT_SEPOLIA_RPC && it.isNotBlank() })
        _state.update { it.copy(safeForm = g) }
    }

    /** eth_call Safe.nonce() (selector 0xaffed0e0) on Sepolia. */
    fun refreshSafeNonce() {
        val f = state.value.safeForm
        if (!SafeTx.addrOk(f.safe)) return
        val api = api()
        scope.launch {
            try {
                val n = SafeTx.hexToDec(api.ethCall(f.rpc, f.safe, "0xaffed0e0"))
                _state.update { it.copy(safeForm = it.safeForm.copy(nonce = n, note = "nonce $n from chain")) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                _state.update { it.copy(safeForm = it.safeForm.copy(note = "couldn't read nonce: ${e.message?.take(80)}")) }
            } finally {
                api.close()
            }
        }
    }

    /** The form's transaction: a native transfer, or transfer(to, amount) on a listed token. null = the form isn't filled in right. */
    fun safeFormTx(f: SafeForm): SafeTx? {
        val token = Allowlist.token(chainId(), f.token)
        if ((f.token.isNotEmpty() && token == null) || !SafeTx.addrOk(f.to) || !Regex("^(0|[1-9][0-9]*)$").matches(f.nonce)) return null
        val units = SafeTx.toUnits(f.amount, token?.decimals ?: 18)?.takeIf { it != "0" } ?: return null
        return if (token == null) SafeTx(to = f.to, value = units, nonce = f.nonce)
        else SafeTx(to = token.address, data = SafeTx.transferData(f.to, units), nonce = f.nonce)
    }

    /** Check it here, register it with the backend, host a session bound to it. */
    fun hostSafeSpend() {
        val f = state.value.safeForm
        val bad = when {
            !SafeTx.addrOk(f.safe) -> "Safe address: 0x + 40 hex"
            !SafeTx.addrOk(f.to) -> "Recipient: 0x + 40 hex"
            !Regex("^(0|[1-9][0-9]*)$").matches(f.nonce) -> "Nonce: read it from the chain first"
            else -> null
        }
        val tx = safeFormTx(f)
        if (bad != null || tx == null) {
            _state.update { it.copy(error = bad ?: "Amount: a number above 0") }
            return
        }
        startHost { registerSpend(f.safe, tx) }
    }

    private suspend fun registerSpend(safe: String, tx: SafeTx): JsonObject {
        val chain = chainId()
        val context = SafeTx.context(chain, safe, tx)
        val g = gate(context, tx.json(), chain, safe)
        if (g is ContextGate.Result.Refused) throw SpendRefused(g)
        val spend = (g as ContextGate.Result.Ok).spend
        val created = withBackend { it.createSpend(chain, safe, tx.json()) }
        if (created.ctx_hash != spend.ctxHash) throw SpendRefused(ContextGate.Result.Refused(ContextGate.CONTEXT_MISMATCH, "backend hash"))
        _state.update { it.copy(spend = spend) }
        return context
    }

    private fun gate(context: JsonObject, safeTx: JsonObject, spendChain: Long, spendSafe: String): ContextGate.Result =
        ContextGate.check(context, safeTx, spendChain, spendSafe, Prefs.get("safe.address")?.lowercase(), chainId())

    /** The core doesn't carry safe_tx: fetch it from the Safe backend by the session's ctx_hash, then check it here. */
    private suspend fun guestGate(context: JsonObject): ContextGate.Result {
        val hash = ContextGate.ctxHash(context) ?: return ContextGate.Result.Refused(ContextGate.CONTEXT_MISMATCH, "ctx_hash")
        val row = try {
            withBackend { it.spend(hash) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            return ContextGate.Result.Refused(ContextGate.SPEND_UNAVAILABLE, (e as? PopHttpException)?.code ?: e::class.simpleName ?: "error")
        }
        return gate(context, row.safe_tx, row.chain_id, row.safe)
    }

    private suspend fun refuse(api: PopApi, sid: String, r: ContextGate.Result.Refused) {
        runCatching { api.abort(sid) }
        _state.update { it.copy(error = r.code, status = ContextGate.text(r), spend = null) }
    }

    /** At Confirm: sign "pop-safe-owner-v1" ‖ safeTxHash with the device key, send it to the Safe backend. */
    private suspend fun postOwnerSig(spend: ContextGate.Spend) {
        val key = keystore.load() ?: error("not enrolled")
        val msg = SafeTx.ownerMessage(spend.ctxHash.removePrefix("0x").hexToBytes())
        val sig = withContext(Dispatchers.Default) { key.sign(msg) }
        withBackend { it.ownerSig(spend.ctxHash, key.pubkey.toHex(), "0x" + sig.toHex()) }
        _state.update { it.copy(safe = SafeStatus(ownerSig = "signed")) }
    }

    private fun setSafe(f: (SafeStatus) -> SafeStatus) = _state.update { it.copy(safe = f(it.safe ?: SafeStatus())) }

    private fun resumeSafeDelivery() {
        val p = Prefs.get(SAFE_PENDING)?.split(' ')?.takeIf { it.size == 2 } ?: return
        watchSafe(p[0], p[1])
    }

    /** After a NEAR: deliver the core's presence record, then follow the relay. Both phones do this. */
    private fun watchSafe(ctxHash: String, sid: String) {
        safeJob?.cancel()
        safeJob = scope.launch {
            val api = api()
            val backend = SafeBackend(state.value.safeForm.backend)
            try {
                if (deliverPresence(api, backend, ctxHash, sid)) followRelay(backend, ctxHash)
            } finally {
                api.close()
                backend.close()
            }
        }
    }

    /** Until accepted, a refusal, or the time is up (then again at the next start). True = accepted. */
    private suspend fun deliverPresence(api: PopApi, backend: SafeBackend, ctxHash: String, sid: String): Boolean {
        val end = unixMs() + DELIVERY_MAX_MS
        setSafe { it.copy(delivery = "sending", refused = null) }
        while (unixMs() < end) {
            try {
                val presence = api.resultJson(sid)["presence"] as? JsonObject ?: error("no presence record yet")
                val r = backend.presence(ctxHash, presence)
                Prefs.set(SAFE_PENDING, null)
                setSafe { it.copy(delivery = "accepted", relay = r.relay) }
                return true
            } catch (e: CancellationException) {
                throw e
            } catch (e: PopHttpException) {
                when {
                    e.code == "owner_sigs_missing" -> setSafe { it.copy(delivery = "waiting for the other phone's signature") }
                    e.status >= 500 -> setSafe { it.copy(delivery = "backend error ${e.status}, retrying") }
                    else -> {
                        Prefs.set(SAFE_PENDING, null)
                        setSafe { it.copy(delivery = "refused", refused = safeRefusalText(e.code ?: "http_${e.status}")) }
                        return false
                    }
                }
            } catch (e: Throwable) {
                setSafe { it.copy(delivery = "can't send yet, retrying (${e::class.simpleName})") }
            }
            delay(DELIVERY_RETRY_MS)
        }
        return false
    }

    private fun safeRefusalText(code: String): String = when (code) {
        "unattested_device" -> "This phone can't spend: both phones need an attested key, and one here has none. Unattested iPhones and web devices never can. There's no override."
        "not_near" -> "The record isn't a NEAR, so no spend."
        "expired" -> "Too late: this NEAR is too old to spend on. Start a new spend."
        "context_refused" -> "The backend's allowlist refused this transaction."
        "context_mismatch" -> "The record doesn't match this transaction."
        "bad_chain" -> "The Safe backend runs on another chain."
        "no_spend" -> "The Safe backend doesn't know this spend."
        "bad_record_signature" -> "The Safe backend doesn't trust this core's signature. Check SAFE_CORE_PRESENCE_PUBKEY."
        else -> "The Safe backend refused: $code"
    }

    /** GET /relay until the send settles, ~6 min max. */
    private suspend fun followRelay(backend: SafeBackend, ctxHash: String) {
        val end = unixMs() + RELAY_MAX_MS
        while (unixMs() < end) {
            val r = runCatching { backend.relay(ctxHash) }.getOrNull()
            fun str(k: String) = (r?.result?.get(k) as? kotlinx.serialization.json.JsonPrimitive)?.takeIf { it.isString }?.content
            val st = r?.status
            if (st != null) setSafe {
                it.copy(relay = st, relayText = str("text") ?: str("error"), txHash = str("tx_hash"),
                    txLink = str("link") ?: str("tx_hash")?.let { h -> "https://sepolia.etherscan.io/tx/$h" })
            }
            if (st in setOf("success", "reverted", "skipped", "error")) return
            delay(RELAY_POLL_MS)
        }
    }

    // ---- confirm (§3.3 step 3) ----

    /** POST confirm, then wait for both -> state confirmed, nonce known. Then Run. */
    fun confirmPartner() {
        val id = state.value.session?.session_id ?: return
        run("confirming") { api ->
            state.value.spend?.let { postOwnerSig(it) }
            val v0 = api.confirm(id)
            _state.update { it.copy(session = v0, confirmSent = true, status = "waiting for partner to confirm") }
            // wait for the partner's confirm by state: PopRun started in "joined" would wait for a later attempt instead of arming
            val v = if (v0.state !in PRE_CONFIRM) v0
            else pollUntil(api, id) { it.state !in PRE_CONFIRM } ?: error("confirm timed out")
            if (v.state == "aborted") {
                _state.update { it.copy(error = v.error ?: "aborted", status = "Session aborted.") }
                return@run
            }
            // both confirmed, so the core shows the nonce: it must be the one this spend gives
            val spend = state.value.spend
            if (spend != null && !ContextGate.nonceOk(spend, id, v.not_before, v.nonce)) {
                refuse(api, id, ContextGate.Result.Refused(ContextGate.CONTEXT_MISMATCH, "nonce"))
                return@run
            }
            _state.update { it.copy(session = v, screen = Screen.Run, status = "confirmed", result = null, runBlocked = null) }
            runSession(api, v)
        }
    }

    // ---- run (§4-§8) ----

    fun refreshPreflight() {
        _state.update { it.copy(preflight = runCatching { engine.preflight() }.getOrNull()) }
    }

    fun raiseVolume() {
        runCatching { engine.setMediaVolume(0.8) }
        refreshPreflight()
    }

    /** Start (again) after a blocked pre-flight. */
    fun startRun() {
        val v = state.value.session ?: return
        run("run") { api -> runSession(api, v) }
    }

    private suspend fun runSession(api: PopApi, v: SessionView) {
        val role = (v.role ?: state.value.role)?.singleOrNull() ?: error("no role")
        val key = keystore.load() ?: error("not enrolled")
        refreshPreflight()
        _state.update { it.copy(runBlocked = null, runPhase = RunPhase.Arming, runNote = null) }
        val r = PopRun(
            api, engine, key, v.session_id, role,
            uploadRecordings = state.value.uploadRecordings,
            onStatus = { p, k, note -> _state.update { it.copy(runPhase = p, runAttempt = k, runNote = note ?: if (p == RunPhase.Arming || p == RunPhase.WaitingResult) it.runNote else null, status = "${p.name.lowercase()} (attempt $k)") } },
            model = deviceModel(),
            popt2 = popt2.takeIf { state.value.popt2On },
            calUs = v.self?.cal_us ?: Calibration.load()?.cal_us ?: 0,
        )
        try {
            val res = r.run()
            val ev = r.evidence
            val near = res.verdict == "NEAR" && ev != null && ev.attempt == res.attempt
            _state.update { it.copy(result = res, resultDetail = r.audioError, screen = Screen.Result, runPhase = null, proof = null) }
            val spend = state.value.spend
            if (spend != null && res.verdict == "NEAR") {
                Prefs.set(SAFE_PENDING, "${spend.ctxHash} ${v.session_id}")
                watchSafe(spend.ctxHash, v.session_id)
            }
            if (near) startProof(ev!!, res, allowMetered = false)
        } catch (e: RunBlocked) {
            refreshPreflight()
            _state.update { it.copy(runBlocked = e.message, runPhase = null) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            runCatching { engine.release() }
            runCatching { api.abort(v.session_id) }
            val detail = (e as? PopHttpException)?.let { it.hint ?: it.code ?: "http_${it.status}" } ?: "${e::class.simpleName}: ${e.message}"
            _state.update {
                it.copy(result = ResultRecord(session_id = v.session_id, verdict = "NOT_NEAR", reason = "aborted"),
                    resultDetail = detail, screen = Screen.Result, runPhase = null)
            }
        }
    }

    /** Cancel on the Run screen: stop, release audio, abort the session. */
    fun abortRun() {
        job?.cancel()
        runCatching { engine.release() }
        abortPairing()
    }

    fun again() {
        proofJob?.cancel()
        pendingProof = null
        _state.update { it.copy(session = null, invite = null, joinInvite = null, result = null, resultDetail = null, runPhase = null, runNote = null, runBlocked = null, confirmSent = false, proof = null, spend = null) }
        go(Screen.Home)
    }

    // ---- option A proof (after NEAR) ----

    /** Download the key on a metered network too, or retry after a failure. */
    fun proveNow() {
        val (ev, res) = pendingProof ?: return
        startProof(ev, res, allowMetered = true)
    }

    /**
     * Our half of the option A proof: witness from the signed POPT v2 + capture + codes + SBcred3, constraint
     * check, proof on a background thread, then POST /v1/session/{id}/proof. validAt = the view's valid_at
     * when the server sends one, else t0 of the attempt in unix seconds (port spec §1.4).
     */
    private fun startProof(ev: Popt2Evidence, res: ResultRecord, allowMetered: Boolean) {
        pendingProof = ev to res
        if (keystore.platform == "web" && !ProverLib.available) { // web: no local prover
            if (ev.provable == false) { _state.update { it.copy(proof = ProofStatus.Skipped("Not provable: own arrival is more than 2 ms from the OS timestamp.")) }; return }
            delegateProof(); return
        }
        proofJob?.cancel()
        val set: (ProofStatus) -> Unit = { st -> _state.update { it.copy(proof = st) } }
        _state.update { it.copy(proofBusy = true) }
        proofJob = scope.launch {
            try {
                val key = keystore.load() ?: error("not enrolled")
                val cred = holder.credential(key.pubkey)
                if (cred == null) { set(ProofStatus.Skipped("No SBcred3 credential on this phone (enroll with a server that issues one).")); return@launch }
                if (ev.provable == false) { set(ProofStatus.Skipped("Not provable: own arrival is more than 2 ms from the OS timestamp.")); return@launch }
                val validAt = res.valid_at ?: (ev.t0Ms / 1000)
                val salt = secureRandomBytes(31)
                val src = ProofSource(ev.transcript, ev.sig, ev.capture, ev.own, ev.partner, cred.cred, cred.sig, cred.issuerPub, validAt, salt, ev.tree)
                val out = prover.run(src, allowDownload = allowMetered || networkIsMetered() != true, onStatus = set) ?: return@launch
                val tag = "${ZkFiles.dir()}/proof_${ev.sessionId.take(8)}_${ev.role}${ev.attempt}"
                runCatching { ZkFiles.write("$tag.bin", out.proof); ZkFiles.write("$tag.pub", out.publicInputs) }
                set(ProofStatus.Step("uploading proof"))
                val api = api()
                val up = try {
                    uploadSummary(api.uploadProof(ev.sessionId, ev.attempt, out.built.circuit,
                        com.enconomy.pop.zk.BigNat.fromBytes(salt).toDecimal(), out.proof, out.publicInputs))
                } catch (e: PopHttpException) {
                    proofUploadNote(e)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Throwable) {
                    "upload failed: ${e.message}; kept on the phone"
                } finally {
                    api.close()
                }
                set(ProofStatus.Done(out.stats, up))
            } catch (e: CancellationException) {
                throw e
            } catch (e: UnprovableException) {
                set(ProofStatus.Skipped("Not provable (${e.reason}): ${e.message}"))
            } catch (e: KeyException) {
                set(ProofStatus.Failed("proving key", e.message ?: e.reason))
            } catch (e: ProverException) {
                set(ProofStatus.Failed("prover", e.message ?: e.code))
            } catch (e: Throwable) {
                set(ProofStatus.Failed("proof", "${e::class.simpleName}: ${e.message}"))
            }
        }
        proofJob?.invokeOnCompletion { _state.update { it.copy(proofBusy = proofJob?.isCompleted == false) } }
    }

    /**
     * Delegated proof: same input map and pre-checks as [startProof], no local prove; POST it to
     * /v1/session/{id}/proof/delegate and poll the result's zk block (zkmobile/APP_SERVER_CONTRACT.md).
     */
    fun delegateProof() {
        val (ev, res) = pendingProof ?: return
        proofJob?.cancel()
        val set: (ProofStatus) -> Unit = { st -> _state.update { it.copy(proof = st) } }
        _state.update { it.copy(proofBusy = true) }
        proofJob = scope.launch {
            val api = api()
            try {
                val key = keystore.load() ?: error("not enrolled")
                val cred = holder.credential(key.pubkey)
                if (cred == null) { set(ProofStatus.Skipped("No SBcred3 credential on this phone (enroll with a server that issues one).")); return@launch }
                val validAt = res.valid_at ?: (ev.t0Ms / 1000)
                val salt = secureRandomBytes(31)
                val src = ProofSource(ev.transcript, ev.sig, ev.capture, ev.own, ev.partner, cred.cred, cred.sig, cred.issuerPub, validAt, salt, ev.tree)
                set(ProofStatus.Step("building witness input"))
                val built = withContext(Dispatchers.Default) { WitnessInput.build(src) }
                set(ProofStatus.Step("sending inputs to the server"))
                val (st, body) = api.delegateProof(ev.sessionId, ev.attempt, built.circuit,
                    com.enconomy.pop.zk.BigNat.fromBytes(salt).toDecimal(), built.json)
                val role = ev.role.toString()
                fun zkOf(o: JsonObject): JsonObject? = (o["zk"] as? JsonObject)?.get(role) as? JsonObject
                var entry = runCatching { zkOf(popJson.parseToJsonElement(body).jsonObject) }.getOrNull()
                val t0 = monoNanos()
                set(ProofStatus.Step("server proving"))
                while (entry?.get("status")?.jsonPrimitive?.content !in setOf("verified", "rejected")) {
                    if (st != 202 && st != 200) break
                    if ((monoNanos() - t0) / 1_000_000 > 180_000) { set(ProofStatus.Failed("delegate", "server did not finish in 3 min")); return@launch }
                    delay(2000)
                    entry = runCatching { zkOf(api.resultJson(ev.sessionId)) }.getOrNull()
                }
                val status = entry?.get("status")?.jsonPrimitive?.content
                val secs = (monoNanos() - t0) / 1_000_000_000
                if (status == "verified") set(ProofStatus.Delegated("Server proved and verified our half (${secs} s after upload).", true))
                else set(ProofStatus.Failed("delegate", "server: ${entry?.get("reason")?.jsonPrimitive?.content ?: status ?: "no result"}"))
            } catch (e: CancellationException) {
                throw e
            } catch (e: UnprovableException) {
                set(ProofStatus.Skipped("Not provable (${e.reason}): ${e.message}"))
            } catch (e: PopHttpException) {
                set(ProofStatus.Failed("delegate", if (e.status == 404 || e.status == 405) "server takes no delegated proofs" else "${e.code ?: e.status}: ${e.message}"))
            } catch (e: Throwable) {
                set(ProofStatus.Failed("delegate", "${e::class.simpleName}: ${e.message}"))
            } finally {
                api.close()
            }
        }
        proofJob?.invokeOnCompletion { _state.update { it.copy(proofBusy = proofJob?.isCompleted == false) } }
    }

    // ---- audio check ----

    fun openAudioCheck() {
        go(Screen.AudioCheck)
        val modes = runCatching { engine.sessionModes }.getOrDefault(emptyList())
        val inputs = runCatching { engine.inputPresets }.getOrDefault(emptyList())
        val input = Prefs.get(INPUT_PRESET_PREF)?.takeIf { k -> inputs.any { it.first == k } }
            ?: runCatching { engine.defaultInputPreset }.getOrDefault("")
        val mode = Prefs.get(engine.modePrefKey)?.takeIf { it in modes } ?: engine.defaultMode.takeIf { it in modes }
            ?: modes.firstOrNull() ?: ""
        _state.update {
            it.copy(audioModes = modes, audioMode = mode, audioInputs = inputs, audioInput = input, audioCheck = null, audioRoute = runCatching { engine.route() }.getOrNull(),
                audioModeTitle = engine.modeTitle, audioModeNote = runCatching { engine.modeNote() }.getOrDefault(""))
        }
        if (state.value.serverTuneDb == null) checkConfig()
    }

    /** Audio check only: tune boost in dB (the server's POP_TUNE_DB sets the real play sound). */
    fun setTuneDb(db: Double) {
        if (state.value.audioCheckRunning) return
        _state.update { it.copy(audioTuneDb = db, audioCheck = null) }
    }

    /** iOS session mode for the check and for real runs (Prefs "audio.mode"). */
    fun setAudioMode(m: String) {
        if (state.value.audioCheckRunning) return
        Prefs.set(engine.modePrefKey, m)
        _state.update { it.copy(audioMode = m, audioCheck = null) }
        refreshPreflight() // re-applies the session with the new mode
        _state.update {
            it.copy(audioRoute = runCatching { engine.route() }.getOrNull(), audioModeNote = runCatching { engine.modeNote() }.getOrDefault(""))
        }
    }

    /** Android mic input preset for the check and for real runs (Prefs "audio.input"). */
    fun setAudioInput(k: String) {
        if (state.value.audioCheckRunning) return
        Prefs.set(INPUT_PRESET_PREF, k)
        _state.update { it.copy(audioInput = k, audioCheck = null) }
    }

    fun setForceSpeaker(on: Boolean) {
        if (state.value.audioCheckRunning) return
        _state.update { it.copy(forceSpeaker = on, audioCheck = null) }
    }

    /**
     * Plays the local JBL250 stand-in through the run's own path (prepare + run with a role A plan,
     * sound at t0, 0.5 s quiet lead-in) and measures how loud the phone hears itself.
     */
    /** One audio check through the run's own path; engine released after. Throws when the mic is refused. */
    private suspend fun checkOnce(forceSpeaker: Boolean, tuneDb: Double): AudioCheckResult {
        engine.setForceSpeaker(forceSpeaker)
        val pre = engine.preflight()
        _state.update { it.copy(preflight = pre) }
        if (!pre.micPermission) error("Microphone permission needed.")
        val sr = pre.sampleRate
        val mix = withContext(Dispatchers.Default) { TestSound.generate(sr, tuneDb) }
        engine.prepare(sr, mix.play)
        val before = engine.route()
        val plan = RunPlan('A', sr, 0L, monoNanos() + 1_400_000_000L)
        val cap = engine.run(plan)
        engine.release()
        val lv = withContext(Dispatchers.Default) { cap.selfHear() }
        val off = withContext(Dispatchers.Default) {
            runCatching { SelfOffset.measure(cap, TestSound.parts(sr).first) }.getOrElse {
                SelfOffset(sr, null, null, null, Popt2Config.DELTA_MS * sr / 1000, "error: ${it.message}")
            }
        }
        val path = cap.pathFacts()
        val res = AudioCheckResult(cap.route ?: before, lv, cap.tsSource, cap.outputLatencyMs, pre.problems + pre.warnings,
            mix.requestedDb, mix.appliedDb, mix.peak, off, path)
        println("PopAudio check ${res.verdict} route=${res.route} levels=$lv")
        println("POPCHECK preset=${cap.extraMeta["input_preset_requested"]?.toInt() ?: cap.micSource} " +
            "granted=${cap.extraMeta["input_preset_granted"]?.toInt() ?: cap.micSource} sod=${off.frames} " +
            "ms=${off.ms?.let { kotlin.math.round(it * 100) / 100 }} within2ms=${off.within} p=${off.pSelf} a=${off.aSelf} " +
            "score=${kotlin.math.round(off.score * 1000) / 1000} reason=${off.reason} " +
            path.joinToString(" ") { (k, v) -> "$k=[${v}]" } + " margin=${SelfHear.r1(lv.highMarginDb)}")
        return res
    }

    /** Audio path the runs use: backend / session mode, plus the Android input preset when there is one. */
    private fun backendName(): String {
        val mode = Prefs.get(engine.modePrefKey) ?: engine.defaultMode
        val input = runCatching { engine.inputPresets }.getOrDefault(emptyList())
            .takeIf { it.isNotEmpty() }?.let { Prefs.get(INPUT_PRESET_PREF) ?: engine.defaultInputPreset }
        return listOfNotNull(mode, input).joinToString("/").take(64)
    }

    /**
     * Enrollment calibration: CAL_N audio checks on the speaker, each self offset (same self_os_delta math as a
     * run) in µs, median by [Calibration.fromSamples]. Throws [CalibrationException] when a check misses its own
     * sound or the rule rejects.
     */
    private suspend fun measureCalibration(): CalibrationReq {
        val us = mutableListOf<Long>()
        var sr = 0
        var route = ""
        try {
            for (i in 1..PopConstants.CAL_N) {
                _state.update { it.copy(status = "calibrating $i/${PopConstants.CAL_N}") }
                val r = checkWithRetry()
                val off = r.offset
                val f = off?.frames ?: throw CalibrationException("check $i: own sound not found (${off?.reason ?: "no offset"})")
                if (sr != 0 && off.sr != sr) throw CalibrationException("sample rate changed ${sr} -> ${off.sr}")
                sr = off.sr
                route = r.route.output
                us += Calibration.framesToUs(f, sr)
            }
        } finally {
            runCatching { engine.release() }
            engine.setForceSpeaker(true)
        }
        val cal = Calibration.fromSamples(us)
        println("POPCAL cal_us=$cal samples=$us sr=$sr route=$route backend=${backendName()}")
        return CalibrationReq(cal, sr, route.take(64), backendName(), us.toList())
    }

    /** One calibration check; a failed capture (the web mic drops blocks) gets up to CAL_CAPTURE_TRIES tries. */
    private suspend fun checkWithRetry(): AudioCheckResult {
        var tries = 0
        while (true) {
            try {
                return checkOnce(forceSpeaker = true, tuneDb = state.value.serverTuneDb ?: 0.0)
            } catch (e: AudioException) {
                tries += 1
                if (e.reason != "capture_failed" || tries >= CAL_CAPTURE_TRIES) throw e
                println("POPCAL capture retry $tries: ${e.message}")
            }
        }
    }

    /** Recalibrate: new calibration, sent signed (POST /v1/device/calibration), kept locally on success. */
    fun recalibrate() = run("calibrating") { api ->
        val c = try {
            measureCalibration()
        } catch (e: CalibrationException) {
            _state.update { it.copy(error = "Calibration rejected: ${e.message}", status = "") }
            return@run
        }
        val resp = api.recalibrate(c)
        val got = resp.calibration?.cal_us ?: error("server kept no calibration")
        check(got == c.cal_us) { "server cal_us $got != ${c.cal_us}" }
        Calibration.save(c)
        _state.update { it.copy(enrollment = it.enrollment?.copy(calUs = c.cal_us), status = "calibrated: ${Calibration.text(c.cal_us)}") }
    }

    fun audioCheck() {
        if (state.value.busy || state.value.audioCheckRunning) return
        _state.update { it.copy(audioCheckRunning = true, audioCheck = null, error = null, status = "audio check") }
        job = scope.launch {
            try {
                val res = checkOnce(state.value.forceSpeaker, state.value.tuneDb)
                _state.update {
                    it.copy(audioCheck = res, audioRoute = res.route, status = "audio check: ${res.verdict}",
                        audioModeNote = runCatching { engine.modeNote() }.getOrDefault(""))
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                _state.update { it.copy(error = "Audio check failed: ${e.message}", status = "") }
            } finally {
                runCatching { engine.release() }
                engine.setForceSpeaker(true)
                _state.update { it.copy(audioCheckRunning = false) }
            }
        }
    }

    // ---- prover bench ----

    fun openBench() {
        go(Screen.Bench)
        refreshKeys()
    }

    fun refreshKeys() {
        val ks = ProvingKeys.all
        val st = when {
            ks.all { keyCache.present(it) } -> "downloaded"
            ks.none { keyCache.present(it) || keyCache.partial(it) > 0 } -> "missing"
            else -> "partly downloaded"
        }
        _state.update { it.copy(keyState = st) }
    }

    private fun benchLog(line: String) {
        println("PopBench: $line")
        _state.update { it.copy(benchLog = it.benchLog + line) }
        runCatching { ZkFiles.append("${ZkFiles.dir()}/bench.log", "$line\n".encodeToByteArray()) }
    }

    /** Fetches every missing prover file (circuit, CRS, vk). */
    fun benchDownload() {
        if (benchJob?.isActive == true) return
        benchJob = scope.launch {
            _state.update { it.copy(benchStatus = null, benchLog = listOf("prover files: ${if (networkIsMetered() == true) "on a metered network" else "downloading"}")) }
            try {
                val t0 = monoNanos()
                for (k in ProvingKeys.all) keyCache.ensure(k) { d, n -> _state.update { it.copy(benchStatus = ProofStatus.Downloading(d, n)) } }
                benchLog("prover files ok in ${ProofStats.ms((monoNanos() - t0) / 1_000_000)} (sha256 pinned)")
                _state.update { it.copy(benchStatus = null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                _state.update { it.copy(benchStatus = ProofStatus.Failed("prover files", e.message ?: "")) }
            } finally {
                refreshKeys()
            }
        }
    }

    fun benchDeleteKeys() {
        if (benchJob?.isActive == true) return
        ProvingKeys.all.forEach(keyCache::delete)
        refreshKeys()
    }

    /** Proves a bundled fixture: witness parity with the spike, then key load / check / prove, time and memory. */
    @OptIn(ExperimentalResourceApi::class)
    fun benchRun(name: String, force: Boolean = false) {
        if (benchJob?.isActive == true) return
        if (proofJob?.isCompleted == false || ProofRunner.busy) {
            _state.update { it.copy(benchStatus = ProofStatus.Skipped("A session proof is still running; retry when it is done.")) }
            return
        }
        benchJob = scope.launch { ProofRunner.awake {
            val m = DeviceMemory.info()
            _state.update {
                it.copy(benchStatus = ProofStatus.Step("loading fixture"), benchLog = listOf(
                    "fixture $name", "native: ${ProverLib.loadError ?: ProverLib.version()}",
                    "device RAM ${ProofStats.mb(m.totalBytes)}" + (m.availBytes?.let { a -> ", free ${ProofStats.mb(a)}" } ?: ""),
                ))
            }
            try {
                val fx = BenchFixture.parse(Res.readBytes("files/zk/bench_$name.json").decodeToString())
                val t0 = monoNanos()
                val built = withContext(Dispatchers.Default) { WitnessInput.build(fx.source) }
                val bad = withContext(Dispatchers.Default) { fx.fieldMismatches(built) }
                benchLog("witness input ${ProofStats.ms((monoNanos() - t0) / 1_000_000)} (tree + I/Q), " +
                    if (bad.isEmpty()) "all ${built.fields.size} inputs = team Prover.toml" else "DIFFERS from Prover.toml: ${bad.joinToString()}")
                if (built.halfCommit.toDecimal() != fx.halfCommit) benchLog("halfCommit DIFFERS from the team's proof")
                if (!built.expectedPublic.contentEquals(fx.publicInputs)) benchLog("expected public inputs DIFFER from the team's proof")
                val out = prover.run(fx.source, allowDownload = true, onStatus = { st -> _state.update { it.copy(benchStatus = st) } },
                    force = force, expectPublic = fx.publicInputs, prebuilt = built)
                if (out == null) benchLog("not proved: ${state.value.benchStatus}")
                if (out != null) {
                    out.stats.lines().forEach(::benchLog)
                    runCatching {
                        ZkFiles.write("${ZkFiles.dir()}/bench_$name.proof", out.proof)
                        ZkFiles.write("${ZkFiles.dir()}/bench_$name.pub", out.publicInputs)
                        benchLog("saved bench_$name.proof / .pub")
                    }
                    _state.update { it.copy(benchStatus = ProofStatus.Done(out.stats, null)) }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                val step = when (e) { is KeyException -> "proving key"; is ProverException -> "prover"; is UnprovableException -> "witness"; else -> "bench" }
                benchLog("FAILED ($step): ${e.message ?: e::class.simpleName}")
                _state.update { it.copy(benchStatus = ProofStatus.Failed(step, e.message ?: e::class.simpleName ?: "error")) }
            } finally {
                refreshKeys()
            }
        } }
    }

    /** Leave pairing: best-effort abort of the server session. */
    fun abortPairing() {
        val id = state.value.session?.session_id ?: state.value.invite?.session_id
        go(Screen.Home)
        _state.update { it.copy(joinInvite = null, invite = null, session = null, confirmSent = false, spend = null) }
        if (id == null) return
        val api = api()
        scope.launch {
            try { api.abort(id) } catch (e: CancellationException) { throw e } catch (_: Throwable) {} finally { api.close() }
        }
    }
}
