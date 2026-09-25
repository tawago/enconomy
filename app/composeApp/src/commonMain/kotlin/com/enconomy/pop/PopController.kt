package com.enconomy.pop

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

const val DEFAULT_BASE_URL = "http://192.168.0.34:8000"

enum class Screen { Enroll, Home, Host, Join, Confirm, Run, Result }

data class Enrollment(val deviceId: String, val serverUrl: String, val displayName: String, val attested: Boolean, val securityLevel: String)

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
)

/**
 * App shell state. Enrollment is keyed on the device key only; a server that does not
 * know the device rejects signed calls (unknown_device) and the user re-enrolls.
 * Host/Join need a matching /v1/config (§1), checked at startup and on ping.
 * Pairing (§3): Host -> Inviting (QR + HCE), Join -> Scanning (NFC reader + camera),
 * both -> Confirm. Run / result plug in after Confirm (Screen.Run).
 */
class PopController(
    private val keystore: DeviceKeystore,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Main),
) {
    private val _state = MutableStateFlow(initial())
    val state: StateFlow<UiState> = _state
    private var job: Job? = null

    init { checkConfig() }

    private fun initial(): UiState {
        val url = Prefs.get("baseUrl") ?: DEFAULT_BASE_URL
        val name = Prefs.get("displayName") ?: deviceModel().take(32)
        val e = storedEnrollment()
        return UiState(baseUrl = url, displayName = name, enrollment = e, screen = if (e != null) Screen.Home else Screen.Enroll)
    }

    private fun storedEnrollment(): Enrollment? {
        val key = keystore.load() ?: return null
        val id = Prefs.get("enroll.deviceId") ?: return null
        if (id != key.deviceId) return null
        return Enrollment(id, Prefs.get("enroll.url") ?: "", Prefs.get("enroll.name") ?: "", Prefs.get("enroll.attested") == "1", key.securityLevel)
    }

    fun api(): PopApi = PopApi(state.value.baseUrl, key = { keystore.load() })

    fun setBaseUrl(url: String) {
        Prefs.set("baseUrl", url)
        _state.update { it.copy(baseUrl = url, configOk = null) }
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
                _state.update { it.copy(error = e.code ?: "http_${e.status}", status = e.message ?: "") }
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

    /** §2.2: nonce -> key with attestation challenge -> POST /v1/enroll. */
    fun enroll() = run("enrolling") { api ->
        val name = state.value.displayName.trim()
        require(name.length in 1..32) { "display name 1..32 chars" }
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
            ),
        )
        check(resp.device_id == k.deviceId) { "server device_id ${resp.device_id} != ${k.deviceId}" }
        val url = state.value.baseUrl
        Prefs.set("enroll.deviceId", k.deviceId)
        Prefs.set("enroll.url", url)
        Prefs.set("enroll.name", name)
        Prefs.set("enroll.attested", if (resp.attested) "1" else "0")
        val e = Enrollment(k.deviceId, url, name, resp.attested, k.securityLevel)
        _state.update { it.copy(enrollment = e, screen = Screen.Home, status = "enrolled") }
    }

    fun forgetKey() {
        job?.cancel()
        keystore.delete()
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
        _state.update {
            it.copy(configOk = bad.isEmpty(), error = if (bad.isEmpty()) it.error else "config_mismatch: ${bad.joinToString()}")
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
            _state.update { it.copy(session = v, screen = Screen.Run, status = "confirmed") }
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
