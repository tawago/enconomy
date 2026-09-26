package com.enconomy.pop

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
import kotlinx.coroutines.CoroutineScope
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
import org.jetbrains.compose.resources.ExperimentalResourceApi

/** Build-time server URL (-Ppop.serverUrl / POP_SERVER_URL, see app/README.md). A saved Prefs value wins. */
val DEFAULT_BASE_URL: String = PopBuildConfig.SERVER_URL

/** Prefs key of the iOS audio session mode ("measurement" | "default" | "videoRecording"); Android uses "audio.backend". */
const val AUDIO_MODE_PREF = "audio.mode"

/** iOS session mode when Prefs has none: videoRecording hears itself ~35 dB over the floor (measurement ~18 dB). */
const val DEFAULT_AUDIO_MODE = "videoRecording"

enum class Screen { Enroll, Home, Host, Join, Confirm, Run, Result, Bench, AudioCheck }

data class Enrollment(
    val deviceId: String,
    val serverUrl: String,
    val displayName: String,
    val attested: Boolean,
    val securityLevel: String,
    /** SBcred3 expiry (unix s), null = no credential (v1 server, or it was rejected). */
    val credExpiry: Long? = null,
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
    val keyState: Map<String, String> = emptyMap(),
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
class PopController(
    private val keystore: DeviceKeystore,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Main),
    engineFactory: () -> AudioEngine = ::createAudioEngine,
    holderFactory: () -> HolderStore = { HolderStore(createSecretStore(), PrefsKeyValue) },
) {
    private val engine: AudioEngine by lazy(engineFactory)
    private val holder: HolderStore by lazy(holderFactory)
    private val _state = MutableStateFlow(initial())
    val state: StateFlow<UiState> = _state
    private var job: Job? = null
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

    init { checkConfig() }

    private fun initial(): UiState {
        val url = Prefs.get("baseUrl") ?: DEFAULT_BASE_URL
        val name = Prefs.get("displayName") ?: deviceModel().take(32)
        val e = storedEnrollment()
        return UiState(baseUrl = url, displayName = name, enrollment = e, screen = if (e != null) Screen.Home else Screen.Enroll,
            popt2On = Prefs.get("popt") != "1", audioMode = Prefs.get(AUDIO_MODE_PREF) ?: "")
    }

    private fun storedEnrollment(): Enrollment? {
        val key = keystore.load() ?: return null
        val id = Prefs.get("enroll.deviceId") ?: return null
        if (id != key.deviceId) return null
        return Enrollment(
            id, Prefs.get("enroll.url") ?: "", Prefs.get("enroll.name") ?: "", Prefs.get("enroll.attested") == "1", key.securityLevel,
            holder.credential(key.pubkey)?.expiry,
        )
    }

    fun api(): PopApi = PopApi(state.value.baseUrl, key = { keystore.load() })

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
    fun enroll() = run("enrolling") { api ->
        val name = state.value.displayName.trim()
        require(name.length in 1..32) { "display name 1..32 chars" }
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
        val e = Enrollment(k.deviceId, url, name, resp.attested, k.securityLevel, holder.credential(k.pubkey)?.expiry)
        _state.update { it.copy(enrollment = e, screen = Screen.Home, status = "enrolled", error = credErr) }
    }

    fun forgetKey() {
        job?.cancel()
        keystore.delete()
        holder.clearCredential()
        Prefs.set("enroll.deviceId", null)
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
        _state.update {
            it.copy(uploadRecordings = up, serverTuneDb = tune ?: it.serverTuneDb, configOk = bad.isEmpty(), popt2Available = v2 != null,
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
    fun host() {
        go(Screen.Host)
        _state.update { it.copy(invite = null, session = null, role = "A", confirmSent = false) }
        run("creating session") { api ->
            requireConfig(api)
            val me = keystore.load() ?: error("not enrolled")
            try {
                while (true) {
                    val inv = api.createSession()
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
        _state.update { it.copy(joinInvite = inv, role = "B", confirmSent = false, session = null) }
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
            _state.update { it.copy(session = v, screen = Screen.Confirm, status = "joined") }
        }
    }

    // ---- confirm (§3.3 step 3) ----

    /** POST confirm, then wait for both -> state confirmed, nonce known. Then Run. */
    fun confirmPartner() {
        val id = state.value.session?.session_id ?: return
        run("confirming") { api ->
            val v0 = api.confirm(id)
            _state.update { it.copy(session = v0, confirmSent = true, status = "waiting for partner to confirm") }
            val v = if (v0.state == "confirmed" || v0.nonce != null) v0
            else pollUntil(api, id) { it.state == "confirmed" || it.nonce != null } ?: error("confirm timed out")
            if (v.state == "aborted") {
                _state.update { it.copy(error = v.error ?: "aborted", status = "Session aborted.") }
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
        )
        try {
            val res = r.run()
            val ev = r.evidence
            val near = res.verdict == "NEAR" && ev != null && ev.attempt == res.attempt
            _state.update { it.copy(result = res, resultDetail = r.audioError, screen = Screen.Result, runPhase = null, proof = null) }
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
        _state.update { it.copy(session = null, invite = null, joinInvite = null, result = null, resultDetail = null, runPhase = null, runNote = null, runBlocked = null, confirmSent = false, proof = null) }
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
                runCatching { ZkFiles.write("${ZkFiles.dir()}/proof_${ev.sessionId.take(8)}_${ev.role}${ev.attempt}.bin", out.proof) }
                set(ProofStatus.Step("uploading proof"))
                val api = api()
                val up = try {
                    uploadSummary(api.uploadProof(ev.sessionId, ev.attempt, out.built.circuit,
                        com.enconomy.pop.zk.BigNat.fromBytes(salt).toDecimal(), out.proof))
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
    fun audioCheck() {
        if (state.value.busy || state.value.audioCheckRunning) return
        _state.update { it.copy(audioCheckRunning = true, audioCheck = null, error = null, status = "audio check") }
        job = scope.launch {
            try {
                engine.setForceSpeaker(state.value.forceSpeaker)
                val pre = engine.preflight()
                _state.update { it.copy(preflight = pre) }
                if (!pre.micPermission) error("Microphone permission needed.")
                val sr = pre.sampleRate
                val tuneDb = state.value.tuneDb
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
        val m = ProvingKeys.all.associate { k ->
            k.circuit to when {
                keyCache.present(k) -> "downloaded (${ProofStats.mb(k.size)})"
                keyCache.partial(k) > 0 -> "partial ${ProofStats.mb(keyCache.partial(k))} of ${ProofStats.mb(k.size)}"
                else -> "missing (${ProofStats.mb(k.size)} download)"
            }
        }
        _state.update { it.copy(keyState = m) }
    }

    private fun benchLog(line: String) = _state.update { it.copy(benchLog = it.benchLog + line) }

    fun benchDownload(k: KeySpec) {
        if (benchJob?.isActive == true) return
        benchJob = scope.launch {
            _state.update { it.copy(benchStatus = null, benchLog = listOf("key ${k.circuit}: ${if (networkIsMetered() == true) "on a metered network" else "downloading"}")) }
            try {
                val t0 = monoNanos()
                keyCache.ensure(k) { d, n -> _state.update { it.copy(benchStatus = ProofStatus.Downloading(d, n)) } }
                benchLog("key ok in ${ProofStats.ms((monoNanos() - t0) / 1_000_000)} (sha256 pinned)")
                _state.update { it.copy(benchStatus = null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                _state.update { it.copy(benchStatus = ProofStatus.Failed("proving key", e.message ?: "")) }
            } finally {
                refreshKeys()
            }
        }
    }

    fun benchDeleteKey(k: KeySpec) {
        if (benchJob?.isActive == true) return
        keyCache.delete(k)
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
        benchJob = scope.launch {
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
                    if (bad.isEmpty()) "all ${built.fields.size} fields = spike" else "DIFFERS from spike: ${bad.joinToString()}")
                if (built.halfCommit.toDecimal() != fx.halfCommit) benchLog("halfCommit DIFFERS from spike")
                val out = prover.run(fx.source, allowDownload = true, onStatus = { st -> _state.update { it.copy(benchStatus = st) } },
                    force = force, expectPublicSha = fx.publicSha, prebuilt = built)
                if (out != null) {
                    out.stats.lines().forEach(::benchLog)
                    _state.update { it.copy(benchStatus = ProofStatus.Done(out.stats, null)) }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                val step = when (e) { is KeyException -> "proving key"; is ProverException -> "prover"; is UnprovableException -> "witness"; else -> "bench" }
                _state.update { it.copy(benchStatus = ProofStatus.Failed(step, e.message ?: e::class.simpleName ?: "error")) }
            } finally {
                refreshKeys()
            }
        }
    }

    /** Leave pairing: best-effort abort of the server session. */
    fun abortPairing() {
        val id = state.value.session?.session_id ?: state.value.invite?.session_id
        go(Screen.Home)
        _state.update { it.copy(joinInvite = null, invite = null, session = null, confirmSent = false) }
        if (id == null) return
        val api = api()
        scope.launch {
            try { api.abort(id) } catch (e: CancellationException) { throw e } catch (_: Throwable) {} finally { api.close() }
        }
    }
}
