package com.enconomy.pop

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.enconomy.pop.zk.BenchFixture
import com.enconomy.pop.zk.ProofStats
import com.enconomy.pop.zk.ProofStatus
import com.enconomy.pop.zk.ProverLib
import com.enconomy.pop.zk.ProvingKeys

@Composable
fun App(c: PopController) {
    val s by c.state.collectAsState()
    MaterialTheme {
        Surface(Modifier.fillMaxSize()) {
            Column(
                Modifier.safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("Proof of presence", style = MaterialTheme.typography.headlineSmall)
                OutlinedTextField(
                    value = s.baseUrl,
                    onValueChange = c::setBaseUrl,
                    label = { Text("Server URL") },
                    singleLine = true,
                    enabled = !s.busy,
                    modifier = Modifier.fillMaxWidth(),
                )
                if (s.baseUrl != DEFAULT_BASE_URL) {
                    TextButton(onClick = c::resetBaseUrl, enabled = !s.busy) { Text("Reset to $DEFAULT_BASE_URL", fontSize = 13.sp) }
                }
                when (s.screen) {
                    Screen.Enroll -> Enroll(s, c)
                    Screen.Home -> Home(s, c)
                    Screen.Host -> Host(s, c)
                    Screen.Join -> Join(s, c)
                    Screen.Confirm -> Confirm(s, c)
                    Screen.Run -> Run(s, c)
                    Screen.Result -> Result(s, c)
                    Screen.Bench -> Bench(s, c)
                    Screen.AudioCheck -> AudioCheck(s, c)
                }
                if (s.status.isNotEmpty()) Text("Status: ${s.status}", fontSize = 13.sp, color = Color.Gray)
                s.error?.let { Text(it, color = Color(0xFFC62828), fontWeight = FontWeight.Medium) }
                s.info?.let { Mono(it) }
            }
        }
    }
}

@Composable
private fun Enroll(s: UiState, c: PopController) {
    Text("Enroll this phone", fontWeight = FontWeight.Medium)
    Text("Creates a hardware P-256 key (StrongBox / Secure Enclave) and registers it with the server.", fontSize = 13.sp)
    OutlinedTextField(
        value = s.displayName,
        onValueChange = c::setDisplayName,
        label = { Text("Display name") },
        singleLine = true,
        enabled = !s.busy,
        modifier = Modifier.fillMaxWidth(),
    )
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = c::enroll, enabled = !s.busy && s.displayName.isNotBlank()) { Text("Enroll") }
        OutlinedButton(onClick = c::ping, enabled = !s.busy) { Text("Ping server") }
    }
}

@Composable
private fun Home(s: UiState, c: PopController) {
    val e = s.enrollment ?: return
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Label("device", e.deviceId)
            Label("name", e.displayName)
            Label("key", "${e.securityLevel}, ${if (e.attested) "attested" else "unattested"}")
            Label("credential", e.credExpiry?.let { "SBcred3, expires ${formatUnixDay(it)}" } ?: "none")
            Label("transcript", when {
                !s.popt2On -> "POPT v1 (v2 off)"
                s.popt2Available == true -> "POPT v2 (48 / 44.1 kHz), else v1"
                s.popt2Available == false -> "POPT v1 (server has no v2)"
                else -> "POPT v2 if the server offers it"
            })
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = c::host, enabled = !s.busy && s.configOk != false) { Text("Host") }
        Button(onClick = c::join, enabled = !s.busy && s.configOk != false) { Text("Join") }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = c::ping, enabled = !s.busy) { Text("Ping server") }
        OutlinedButton(onClick = c::forgetKey, enabled = !s.busy) { Text("Re-enroll") }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        TextButton(onClick = { c.setPopt2(!s.popt2On) }, enabled = !s.busy) {
            Text(if (s.popt2On) "Use POPT v1" else "Use POPT v2", fontSize = 13.sp)
        }
        TextButton(onClick = c::openBench, enabled = !s.busy) { Text("Prover bench", fontSize = 13.sp) }
    }
    OutlinedButton(onClick = c::openAudioCheck, enabled = !s.busy) { Text("Audio check") }
}

private val modeLabel = mapOf("measurement" to "Measurement", "default" to "Default", "videoRecording" to "VideoRecording")

@Composable
private fun AudioCheck(s: UiState, c: PopController) {
    KeepScreenOn(s.audioCheckRunning)
    Text("Audio check", fontWeight = FontWeight.Medium)
    Text("Plays a test sound like the real one through the same audio path, records it and measures how loud " +
        "this phone hears itself. Quiet room, phone on the table, speaker uncovered.", fontSize = 13.sp)
    val busy = s.audioCheckRunning
    if (s.audioModes.isNotEmpty()) {
        Text("Session mode (voice processing off; also used for runs)", fontSize = 12.sp, color = Color.Gray)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for (m in s.audioModes) {
                val label = modeLabel[m] ?: m
                if (m == s.audioMode) Button(onClick = {}, enabled = !busy) { Text(label, fontSize = 12.sp) }
                else OutlinedButton(onClick = { c.setAudioMode(m) }, enabled = !busy) { Text(label, fontSize = 12.sp) }
            }
        }
        TextButton(onClick = { c.setForceSpeaker(!s.forceSpeaker) }, enabled = !busy) {
            Text(if (s.forceSpeaker) "Force speaker: ON (tap for OFF, check only)" else "Force speaker: OFF (tap for ON)", fontSize = 13.sp)
        }
    }
    Text("Tune boost (check only; server tune_db ${s.serverTuneDb?.let { f1(it) } ?: "?"} dB)", fontSize = 12.sp, color = Color.Gray)
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        for (d in TuneBoost.STEPS_DB) {
            val label = if (d == 0.0) "0" else "+${d.toInt()}"
            if (d == s.tuneDb) Button(onClick = {}, enabled = !busy) { Text(label, fontSize = 12.sp) }
            else OutlinedButton(onClick = { c.setTuneDb(d) }, enabled = !busy) { Text(label, fontSize = 12.sp) }
        }
    }
    s.audioRoute?.let { r -> if (s.audioCheck == null) Label("route now", routeText(r)) }
    val askMic = rememberMicPermissionRequest { if (it) c.audioCheck() }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = askMic, enabled = !busy && !s.busy) { Text(if (busy) "Playing…" else "Run check") }
        OutlinedButton(onClick = { c.go(Screen.Home) }) { Text("Back") }
    }
    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
    s.audioCheck?.let { r ->
        val lv = r.levels
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(r.verdict, fontSize = 28.sp, fontWeight = FontWeight.Bold,
                    color = when {
                        r.pass -> Color(0xFF2E7D32)
                        r.route.isSpeaker && lv.verdict == "weak" -> Color(0xFFEF6C00)
                        else -> Color(0xFFC62828)
                    })
                Label("route", routeText(r.route))
                Label("volume", "${kotlin.math.round(r.route.volume * 100).toInt()}%")
                Label("mode", r.route.mode)
                Label("sample rate", "${r.route.sampleRate} Hz, latency ${r.latencyMs?.let { f1(it) } ?: "?"} ms, ts ${r.tsSource}")
                if (r.route.detail.isNotEmpty()) Label("detail", r.route.detail)
                Label("tune boost", "+${f1(r.tuneRequestedDb)} dB asked, +${f1(r.tuneAppliedDb)} dB applied, " +
                    "play peak ${f1(r.playPeak * 100)}% (${f1(20 * kotlin.math.log10(r.playPeak))} dBFS)")
                Mono(
                    "band          self    floor   margin\n" +
                        "200-1600 Hz ${pad(lv.lowDb)} ${pad(lv.floorLowDb)} ${pad(lv.lowMarginDb)}\n" +
                        "2-18 kHz    ${pad(lv.highDb)} ${pad(lv.floorHighDb)} ${pad(lv.highMarginDb)}\n" +
                        "peak        ${lv.peak} (${f1(lv.peakDb)} dBFS), floor ${lv.floorPeak}\n" +
                        "dBFS; OK needs 2-18 kHz margin >= ${SelfHear.OK_MARGIN_DB.toInt()} dB",
                )
            }
        }
        r.warnings.forEach { Text(it, fontSize = 12.sp, color = Color.Gray) }
    }
}

private fun routeText(r: AudioRoute) = r.output + (if (r.outputName.isNotBlank()) " (${r.outputName})" else "")

private fun f1(x: Double) = (kotlin.math.round(x * 10) / 10).toString()

private fun pad(x: Double) = f1(x).padStart(7)

@Composable
private fun Host(s: UiState, c: PopController) {
    Text("Host", fontWeight = FontWeight.Medium)
    val nfc = if (nfcCanHost()) rememberNfcState() else NfcState.Unsupported
    val inv = s.invite
    if (inv == null) Text("creating session…") else {
        val qr = inv.invite_b64url?.let { "pop1:$it" }
        if (qr != null) {
            HceForeground()
            Text(
                when (nfc) {
                    NfcState.On -> "Hold the other phone to the back of this one, or let it scan the QR."
                    NfcState.Off -> "NFC is off. Let the other phone scan the QR."
                    NfcState.Unsupported -> "No NFC here. Let the other phone scan the QR."
                },
                fontSize = 13.sp,
            )
            if (nfc == NfcState.Off) OutlinedButton(onClick = ::openNfcSettings) { Text("Turn on NFC") }
            QrCode(qr, Modifier.fillMaxWidth(0.8f).aspectRatio(1f))
            Label("session", inv.session_id)
            Label("invite", qr)
        }
    }
    s.session?.let { v -> Label("state", "${v.state} (seq ${v.seq}, attempt ${v.attempt})") }
    OutlinedButton(onClick = c::abortPairing) { Text("Cancel") }
}

@Composable
private fun Join(s: UiState, c: PopController) {
    Text("Join", fontWeight = FontWeight.Medium)
    val nfc = rememberNfcState()
    if (!s.busy) {
        if (nfc == NfcState.On) NfcInviteReader(onInvite = c::onNfcInvite, onError = c::onNfcError)
        Text(
            when (nfc) {
                NfcState.On -> "Tap the host phone back to back, or scan its QR."
                NfcState.Off -> "NFC is off. Scan the host's QR."
                NfcState.Unsupported -> "No NFC here. Scan the host's QR."
            },
            fontSize = 13.sp,
        )
        if (nfc == NfcState.Off) OutlinedButton(onClick = ::openNfcSettings) { Text("Turn on NFC") }
        QrScanner(onText = c::onQrText, modifier = Modifier.fillMaxWidth().aspectRatio(1f))
    } else {
        s.joinInvite?.let { Label("invite", "session ${it.sessionId}") }
    }
    OutlinedButton(onClick = c::abortPairing) { Text("Cancel") }
}

@Composable
private fun Confirm(s: UiState, c: PopController) {
    val v = s.session
    val p = v?.partner
    Text("Confirm partner", fontWeight = FontWeight.Medium)
    if (v == null || p == null) {
        Text("no partner")
    } else {
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(p.display_name ?: "(no name)", style = MaterialTheme.typography.titleLarge)
                Label("model", p.model ?: "?")
                Label("key", if (p.attested) "attested" else "unattested")
                Label("device", p.device_id)
            }
        }
        Text("Is this the phone next to you? You are ${if (s.role == "A") "host (A)" else "guest (B)"}.", fontSize = 13.sp)
        val mine = v.role ?: s.role
        val other = if (mine == "A") "B" else "A"
        if (v.confirmed[other] == true) Text("Partner confirmed.", fontSize = 13.sp)
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = c::abortPairing) { Text("Cancel") }
        val askMic = rememberMicPermissionRequest { c.confirmPartner() }
        Button(onClick = askMic, enabled = !s.busy && !s.confirmSent && p != null) {
            Text(if (s.confirmSent) "Waiting…" else "Confirm")
        }
    }
}

private val phaseText = mapOf(
    RunPhase.Arming to "Getting ready…",
    RunPhase.Running to "Listening. Keep the phones side by side.",
    RunPhase.SelfCheck to "Checking own sound…",
    RunPhase.Committing to "Locking in the recording…",
    RunPhase.Measuring to "Measuring distance…",
    RunPhase.Submitting to "Signing and sending…",
    RunPhase.Failing to "Measurement failed.",
    RunPhase.WaitingResult to "Waiting for partner…",
)

@Composable
private fun Run(s: UiState, c: PopController) {
    KeepScreenOn(true)
    Text("Presence check", fontWeight = FontWeight.Medium)
    Text("Keep both phones side by side, speakers free, and stay quiet for a few seconds.", fontSize = 13.sp)
    val ph = s.runPhase
    if (ph != null) {
        Text(phaseText[ph] ?: ph.name, style = MaterialTheme.typography.titleLarge)
        if (s.runAttempt > 0) Text("Second try (attempt ${s.runAttempt}).", fontSize = 13.sp)
    }
    s.runNote?.let { Text(it, color = Color(0xFFEF6C00)) }
    s.runBlocked?.let { msg ->
        Text(msg, color = Color(0xFFC62828), fontWeight = FontWeight.Medium)
        val pre = s.preflight
        val askMic = rememberMicPermissionRequest { c.refreshPreflight() }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (pre != null && !pre.micPermission) OutlinedButton(onClick = askMic) { Text("Allow mic") }
            if (pre != null && pre.volumeFrac < 0.6) OutlinedButton(onClick = c::raiseVolume) { Text("Raise volume") }
            Button(onClick = c::startRun, enabled = !s.busy) { Text("Start") }
        }
    }
    s.preflight?.warnings?.forEach { Text(it, fontSize = 12.sp, color = Color.Gray) }
    OutlinedButton(onClick = c::abortRun) { Text("Cancel") }
}

@Composable
private fun Result(s: UiState, c: PopController) {
    val r = s.result
    KeepScreenOn(false)
    if (r == null) {
        Text("no result")
    } else {
        val near = r.verdict == "NEAR"
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(if (near) "NEAR" else "NOT NEAR", fontSize = 40.sp, fontWeight = FontWeight.Bold,
                    color = if (near) Color(0xFF2E7D32) else Color(0xFFC62828))
                r.flight_cm?.let { Text("flight ${kotlin.math.round(it * 10) / 10} cm", style = MaterialTheme.typography.titleMedium) }
                (r.user_text ?: Reasons.of(r.reason))?.let { Text(it) }
            }
        }
        r.reason?.let { Label("reason", it) }
        s.resultDetail?.let { Label("detail", it) }
        if (r.attempts.isNotEmpty()) Label("attempts", r.attempts.joinToString("\n") { a ->
            listOf("attempt", "outcome", "reason", "by").mapNotNull { k -> a[k]?.toString()?.trim('"')?.takeIf { it != "null" } }.joinToString(" ")
        })
        r.session_id?.let { Label("session", it) }
        s.proof?.let { ProofCard("Option A proof", it, onRetry = c::proveNow) }
    }
    Button(onClick = c::again) { Text("Again") }
}

@Composable
private fun ProofCard(title: String, p: ProofStatus, onRetry: (() -> Unit)?) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, fontWeight = FontWeight.Medium)
            when (p) {
                is ProofStatus.Skipped -> Text(p.why, fontSize = 13.sp, color = Color.Gray)
                is ProofStatus.NeedKey -> {
                    Text("Proving key ${p.circuit} needed (${ProofStats.mb(p.bytes)}). You are on mobile data; Wi-Fi recommended.", fontSize = 13.sp)
                    if (onRetry != null) OutlinedButton(onClick = onRetry) { Text("Download and prove") }
                }
                is ProofStatus.Downloading -> {
                    Text("Downloading proving key ${ProofStats.mb(p.done)} / ${ProofStats.mb(p.total)} (Wi-Fi recommended)", fontSize = 13.sp)
                    LinearProgressIndicator(progress = { if (p.total > 0) (p.done.toFloat() / p.total).coerceIn(0f, 1f) else 0f }, modifier = Modifier.fillMaxWidth())
                }
                is ProofStatus.Step -> {
                    Text(p.name.replaceFirstChar { it.uppercase() } + "…", fontSize = 13.sp)
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                }
                is ProofStatus.Done -> {
                    Text("Proved", color = Color(0xFF2E7D32), fontWeight = FontWeight.Medium)
                    p.upload?.let { Text(it, fontSize = 13.sp) }
                    Mono(p.stats.lines().joinToString("\n"))
                }
                is ProofStatus.Failed -> {
                    Text("Failed (${p.step}): ${p.why}", color = Color(0xFFC62828), fontSize = 13.sp)
                    if (onRetry != null) OutlinedButton(onClick = onRetry) { Text("Retry") }
                }
            }
        }
    }
}

@Composable
private fun Bench(s: UiState, c: PopController) {
    Text("Prover bench", fontWeight = FontWeight.Medium)
    Text("Proves a bundled field fixture on this phone: witness input, key load, constraint check, proof. " +
        "Needs about 2 GB of RAM and the proving key (downloaded once, Wi-Fi recommended).", fontSize = 13.sp)
    Label("native prover", ProverLib.loadError ?: ProverLib.version())
    val running = s.benchStatus is ProofStatus.Step || s.benchStatus is ProofStatus.Downloading
    for (k in ProvingKeys.all) {
        Label("key ${k.circuit} (${k.sampleRate} Hz)", s.keyState[k.circuit] ?: "?")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { c.benchDownload(k) }, enabled = !running) { Text("Download") }
            TextButton(onClick = { c.benchDeleteKey(k) }, enabled = !running) { Text("Delete") }
        }
    }
    for (n in BenchFixture.NAMES) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { c.benchRun(n) }, enabled = !running && !s.proofBusy) { Text("Prove $n") }
            TextButton(onClick = { c.benchRun(n, force = true) }, enabled = !running && !s.proofBusy) { Text("ignore RAM check", fontSize = 12.sp) }
        }
    }
    s.benchStatus?.let { ProofCard("Status", it, onRetry = null) }
    if (s.benchLog.isNotEmpty()) Mono(s.benchLog.joinToString("\n"))
    OutlinedButton(onClick = { c.go(Screen.Home) }, enabled = !running) { Text("Back") }
}

@Composable
private fun Label(k: String, v: String) {
    Column {
        Text(k, fontSize = 12.sp, color = Color.Gray)
        SelectionContainer { Text(v, fontFamily = FontFamily.Monospace, fontSize = 13.sp) }
    }
}

@Composable
private fun Mono(t: String) {
    SelectionContainer { Text(t, fontFamily = FontFamily.Monospace, fontSize = 11.sp) }
}
