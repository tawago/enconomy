package com.enconomy.pop

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.enconomy.pop.ui.Avatar
import com.enconomy.pop.ui.Banner
import com.enconomy.pop.ui.CodeBlock
import com.enconomy.pop.ui.DistanceMeter
import com.enconomy.pop.ui.Expandable
import com.enconomy.pop.ui.FactRow
import com.enconomy.pop.ui.Field
import com.enconomy.pop.ui.Hairline
import com.enconomy.pop.ui.IconTile
import com.enconomy.pop.ui.MarginBar
import com.enconomy.pop.ui.NavRow
import com.enconomy.pop.ui.Panel
import com.enconomy.pop.ui.PhonesDuo
import com.enconomy.pop.ui.Pill
import com.enconomy.pop.ui.Pop
import com.enconomy.pop.ui.PopIcons
import com.enconomy.pop.ui.PopMark
import com.enconomy.pop.ui.PopTheme
import com.enconomy.pop.ui.PrimaryButton
import com.enconomy.pop.ui.PulseRings
import com.enconomy.pop.ui.QuietButton
import com.enconomy.pop.ui.Reveal
import com.enconomy.pop.ui.SecondaryButton
import com.enconomy.pop.ui.SectionLabel
import com.enconomy.pop.ui.Segmented
import com.enconomy.pop.ui.SwitchRow
import com.enconomy.pop.ui.Tone
import com.enconomy.pop.ui.VerdictBadge
import com.enconomy.pop.ui.fmt1
import com.enconomy.pop.zk.BenchFixture
import com.enconomy.pop.zk.ProofStats
import com.enconomy.pop.zk.ProofStatus
import com.enconomy.pop.zk.ProverLib
import com.enconomy.pop.zk.ProvingKeys

@Composable
fun App(c: PopController) {
    val s by c.state.collectAsState()
    PopTheme {
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            Box(Modifier.fillMaxSize()) {
                Backdrop(s.screen)
                Column(
                    Modifier.fillMaxSize()
                        .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))
                        .windowInsetsPadding(WindowInsets.ime),
                ) {
                    TopBar(s, c)
                    key(s.screen) {
                        val enter = remember { Animatable(0f) }
                        LaunchedEffect(Unit) { enter.animateTo(1f, tween(380, easing = FastOutSlowInEasing)) }
                        Column(
                            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())
                                .graphicsLayer { alpha = enter.value; translationY = (1 - enter.value) * 24.dp.toPx() }
                                .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Bottom))
                                .padding(horizontal = 20.dp).padding(top = 4.dp, bottom = 28.dp),
                            verticalArrangement = Arrangement.spacedBy(14.dp),
                        ) {
                            s.error?.let { Banner(it, Tone.Bad, title = "Something went wrong") }
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
                            StatusLine(s)
                        }
                    }
                }
            }
        }
    }
}

/** Soft signal-colored glow behind the top of every screen. */
@Composable
private fun Backdrop(screen: Screen) {
    val pal = Pop.palette
    val tint = if (screen == Screen.Result) Color.Transparent else pal.signal
    Canvas(Modifier.fillMaxSize()) {
        drawRect(
            Brush.radialGradient(
                listOf(tint.copy(alpha = if (pal.dark) 0.13f else 0.10f), Color.Transparent),
                center = Offset(size.width * 0.85f, -size.width * 0.1f), radius = size.width * 1.1f,
            ),
        )
    }
}

@Composable
private fun TopBar(s: UiState, c: PopController) {
    Row(
        Modifier.fillMaxWidth().height(60.dp).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val back: (() -> Unit)? = when (s.screen) {
            Screen.Bench -> { { c.go(Screen.Home) } }
            Screen.AudioCheck -> { { c.go(Screen.Home) } }
            else -> null
        }
        if (back != null) {
            val benchRunning = s.benchStatus is ProofStatus.Step || s.benchStatus is ProofStatus.Downloading
            IconButton(onClick = back, enabled = !(s.screen == Screen.Bench && benchRunning)) {
                Icon(PopIcons.Back, "Back", Modifier.size(24.dp))
            }
        } else {
            Spacer(Modifier.width(8.dp))
            PopMark(28.dp)
            Spacer(Modifier.width(10.dp))
        }
        Text(
            if (back != null) "Home" else "pop",
            style = if (back != null) MaterialTheme.typography.titleMedium else MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
        )
        Spacer(Modifier.weight(1f))
        when (s.configOk) {
            true -> Pill("Server online", Tone.Good, dot = true)
            false -> Pill("Config mismatch", Tone.Bad, dot = true)
            null -> Pill(if (s.busy) "Connecting" else "Not checked", Tone.Neutral, dot = true)
        }
        Spacer(Modifier.width(8.dp))
    }
}

@Composable
private fun PageTitle(title: String, subtitle: String? = null) {
    Column(Modifier.padding(top = 6.dp, bottom = 4.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.headlineMedium)
        if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodyLarge, color = Pop.palette.muted)
    }
}

@Composable
private fun StatusLine(s: UiState) {
    if (s.status.isEmpty()) return
    Row(Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        if (s.busy) CircularProgressIndicator(Modifier.size(10.dp), strokeWidth = 1.5.dp, color = Pop.palette.muted)
        else Box(Modifier.size(6.dp).clip(CircleShape).background(Pop.palette.muted.copy(alpha = 0.6f)))
        Spacer(Modifier.width(8.dp))
        Text(s.status, style = Pop.mono, color = Pop.palette.muted, textAlign = TextAlign.Center)
    }
}

@Composable
private fun popTextFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedContainerColor = Pop.palette.panel,
    unfocusedContainerColor = Pop.palette.panel,
    disabledContainerColor = Pop.palette.panel,
    unfocusedBorderColor = Pop.palette.hairline,
    focusedLabelColor = MaterialTheme.colorScheme.primary,
    unfocusedLabelColor = Pop.palette.muted,
)

// ---------------------------------------------------------------- enroll / home

@Composable
private fun Enroll(s: UiState, c: PopController) {
    Reveal {
        Panel(padding = androidx.compose.foundation.layout.PaddingValues(0.dp), spacing = 0.dp) {
            Box(
                Modifier.fillMaxWidth().height(150.dp).background(
                    Brush.verticalGradient(listOf(Pop.palette.signalSoft, Color.Transparent)),
                ),
                contentAlignment = Alignment.Center,
            ) { PhonesDuo(Modifier.fillMaxWidth(0.75f).height(118.dp)) }
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Proof of presence", style = MaterialTheme.typography.headlineMedium)
                Text(
                    "Two phones prove they are side by side with a short burst of sound. Set up this phone once to get started.",
                    style = MaterialTheme.typography.bodyLarge, color = Pop.palette.muted,
                )
            }
        }
    }
    Reveal(90) {
        Panel {
            OutlinedTextField(
                value = s.displayName,
                onValueChange = c::setDisplayName,
                label = { Text("Display name") },
                supportingText = { Text("Shown to the phone you pair with.") },
                singleLine = true,
                enabled = !s.busy,
                shape = MaterialTheme.shapes.medium,
                colors = popTextFieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
            PrimaryButton(
                if (s.busy) "Setting up…" else "Enroll this phone", c::enroll, Modifier.fillMaxWidth(),
                enabled = s.displayName.isNotBlank(), loading = s.busy, icon = PopIcons.Key,
            )
        }
    }
    Reveal(180) {
        Column(verticalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.padding(vertical = 4.dp)) {
            Feature(PopIcons.Key, "Hardware key", "Creates a P-256 key in StrongBox / Secure Enclave and registers it with the server.")
            Feature(PopIcons.Wave, "Sound, not location", "Distance comes from how long a chirp takes to travel between the phones.")
            Feature(PopIcons.Shield, "On-device proof", "After a match, this phone can prove its half in zero knowledge.")
        }
    }
    Reveal(260) { ServerPanel(s, c) }
}

@Composable
private fun Feature(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, body: String) {
    Row(verticalAlignment = Alignment.Top) {
        IconTile(icon)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(body, style = MaterialTheme.typography.bodyMedium, color = Pop.palette.muted)
        }
    }
}

@Composable
private fun ServerPanel(s: UiState, c: PopController) {
    Panel {
        Expandable("Server", subtitle = s.baseUrl.removePrefix("https://").removePrefix("http://"), icon = PopIcons.Server,
            initiallyOpen = s.configOk == false || s.info != null) {
            OutlinedTextField(
                value = s.baseUrl,
                onValueChange = c::setBaseUrl,
                label = { Text("Server URL") },
                singleLine = true,
                enabled = !s.busy,
                shape = MaterialTheme.shapes.medium,
                colors = popTextFieldColors(),
                textStyle = Pop.mono.copy(fontSize = MaterialTheme.typography.bodyMedium.fontSize),
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                SecondaryButton("Ping server", c::ping, enabled = !s.busy, icon = PopIcons.Refresh, compact = true)
                if (s.baseUrl != DEFAULT_BASE_URL) QuietButton("Reset to default", c::resetBaseUrl, enabled = !s.busy)
            }
            if (s.baseUrl != DEFAULT_BASE_URL) Text("Default: $DEFAULT_BASE_URL", style = Pop.mono, color = Pop.palette.muted)
            s.info?.let { CodeBlock(it) }
        }
    }
}

@Composable
private fun Home(s: UiState, c: PopController) {
    val e = s.enrollment ?: return
    Reveal {
        Panel {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Avatar(e.displayName.ifBlank { "?" })
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(e.displayName.ifBlank { "This phone" }, style = MaterialTheme.typography.titleLarge)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Pill(e.securityLevel, Tone.Accent, icon = PopIcons.Key)
                        if (e.attested) Pill("Attested", Tone.Good, icon = PopIcons.Check) else Pill("Unattested", Tone.Warn)
                    }
                }
            }
            Hairline()
            Expandable("Device details", subtitle = "id ${e.deviceId.take(12)}…") {
                Field("device", e.deviceId)
                Field("key", "${e.securityLevel}, ${if (e.attested) "attested" else "unattested"}")
                Field("credential", e.credExpiry?.let { "SBcred3, expires ${formatUnixDay(it)}" } ?: "none")
                Field("transcript", transcriptText(s))
            }
        }
    }
    if (s.configOk == false) {
        Banner(
            "This server's constants don't match the app, so hosting and joining are off. Check the server URL and ping again.",
            Tone.Bad, title = "Server config mismatch",
        )
    }
    Reveal(80) {
        Panel(padding = androidx.compose.foundation.layout.PaddingValues(0.dp), spacing = 0.dp) {
            Box(
                Modifier.fillMaxWidth().height(150.dp).background(Brush.verticalGradient(listOf(Pop.palette.signalSoft, Color.Transparent))),
                contentAlignment = Alignment.Center,
            ) { PhonesDuo(Modifier.fillMaxWidth(0.75f).height(118.dp)) }
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Check presence", style = MaterialTheme.typography.headlineSmall)
                    Text(
                        "One phone hosts an invite, the other taps or scans it. Then both play a short sound.",
                        style = MaterialTheme.typography.bodyMedium, color = Pop.palette.muted,
                    )
                }
                val ok = !s.busy && s.configOk != false
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    PrimaryButton("Host", c::host, Modifier.weight(1f), enabled = ok, icon = PopIcons.Qr)
                    PrimaryButton("Join", c::join, Modifier.weight(1f), enabled = ok, icon = PopIcons.Scan)
                }
            }
        }
    }
    Reveal(160) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            SectionLabel("Tools")
            Panel(spacing = 4.dp, padding = androidx.compose.foundation.layout.PaddingValues(horizontal = 14.dp, vertical = 8.dp)) {
                NavRow(PopIcons.Speaker, "Audio check", "Test that this phone hears its own sound", c::openAudioCheck, enabled = !s.busy)
                Hairline()
                NavRow(PopIcons.Chip, "Prover bench", "Prove a bundled fixture on this phone", c::openBench, enabled = !s.busy)
                Hairline()
                SwitchRow(
                    "Transcript v2", transcriptText(s), s.popt2On, { c.setPopt2(it) }, enabled = !s.busy, icon = PopIcons.Wave,
                )
            }
        }
    }
    Reveal(220) { ServerPanel(s, c) }
    Reveal(260) {
        Panel(padding = androidx.compose.foundation.layout.PaddingValues(horizontal = 14.dp, vertical = 8.dp)) {
            NavRow(PopIcons.Logout, "Re-enroll", "Forget this phone's key and set it up again", c::forgetKey, enabled = !s.busy, tone = Tone.Bad)
        }
    }
}

private fun transcriptText(s: UiState) = when {
    !s.popt2On -> "POPT v1 (v2 off)"
    s.popt2Available == true -> "POPT v2 (48 / 44.1 kHz), else v1"
    s.popt2Available == false -> "POPT v1 (server has no v2)"
    else -> "POPT v2 if the server offers it"
}

// ---------------------------------------------------------------- pairing

@Composable
private fun NfcPill(nfc: NfcState) = when (nfc) {
    NfcState.On -> Pill("NFC ready", Tone.Good, icon = PopIcons.Nfc)
    NfcState.Off -> Pill("NFC off", Tone.Warn, icon = PopIcons.Nfc)
    NfcState.Unsupported -> Pill("QR only", Tone.Neutral, icon = PopIcons.Qr)
}

@Composable
private fun Host(s: UiState, c: PopController) {
    val nfc = if (nfcCanHost()) rememberNfcState() else NfcState.Unsupported
    val inv = s.invite
    val qr = inv?.invite_b64url?.let { "pop1:$it" }
    PageTitle(
        "Invite a partner",
        when (nfc) {
            NfcState.On -> "Hold the other phone to the back of this one, or let it scan the code."
            NfcState.Off -> "NFC is off. Let the other phone scan the code."
            NfcState.Unsupported -> "No NFC here. Let the other phone scan the code."
        },
    )
    if (qr != null) HceForeground()
    BoxWithConstraints(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        val side = minOf(maxWidth * 0.74f, 300.dp)
        Box(Modifier.fillMaxWidth().height(side * 1.32f), contentAlignment = Alignment.Center) {
            PulseRings(Modifier.fillMaxSize(), periodMs = 3200, startFrac = 0.5f)
            Surface(
                Modifier.size(side).shadow(24.dp, RoundedCornerShape(28.dp), spotColor = Pop.palette.signal.copy(alpha = 0.5f)),
                shape = RoundedCornerShape(28.dp), color = Color.White,
            ) {
                Box(Modifier.padding(16.dp), contentAlignment = Alignment.Center) {
                    if (qr != null) QrCode(qr, Modifier.fillMaxSize())
                    else Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        CircularProgressIndicator(color = Color(0xFF0B9E6F), strokeWidth = 3.dp)
                        Text(if (inv == null) "Creating session…" else "Preparing invite…", color = Color(0xFF3B4250), style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally)) {
        NfcPill(nfc)
        s.session?.let { v -> Pill("${v.state} · seq ${v.seq} · try ${v.attempt}", Tone.Neutral, dot = true) }
            ?: Pill("Waiting for guest", Tone.Accent, dot = true)
    }
    if (nfc == NfcState.Off) SecondaryButton("Turn on NFC", ::openNfcSettings, Modifier.fillMaxWidth(), icon = PopIcons.Nfc)
    if (inv != null && qr != null) {
        Panel {
            Expandable("Invite details", subtitle = "session ${inv.session_id.take(12)}…") {
                Field("session", inv.session_id)
                Field("invite", qr)
            }
        }
    }
    SecondaryButton("Cancel", c::abortPairing, Modifier.fillMaxWidth(), icon = PopIcons.Close)
}

@Composable
private fun Join(s: UiState, c: PopController) {
    val nfc = rememberNfcState()
    PageTitle(
        "Join a partner",
        if (s.busy) "Found an invite. Connecting to the session…" else when (nfc) {
            NfcState.On -> "Tap the host phone back to back, or scan its code."
            NfcState.Off -> "NFC is off. Scan the host's code."
            NfcState.Unsupported -> "No NFC here. Scan the host's code."
        },
    )
    if (!s.busy) {
        if (nfc == NfcState.On) NfcInviteReader(onInvite = c::onNfcInvite, onError = c::onNfcError)
        Box(
            Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(28.dp)).background(Color.Black)
                .border(1.dp, Pop.palette.hairline, RoundedCornerShape(28.dp)),
            contentAlignment = Alignment.Center,
        ) {
            QrScanner(onText = c::onQrText, modifier = Modifier.fillMaxSize())
            ScanOverlay(Modifier.fillMaxSize())
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) { NfcPill(nfc) }
        if (nfc == NfcState.Off) SecondaryButton("Turn on NFC", ::openNfcSettings, Modifier.fillMaxWidth(), icon = PopIcons.Nfc)
    } else {
        Panel {
            Box(Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) {
                PulseRings(Modifier.fillMaxSize())
                PopMark(52.dp)
            }
            s.joinInvite?.let { Field("invite", "session ${it.sessionId}") }
        }
    }
    SecondaryButton("Cancel", c::abortPairing, Modifier.fillMaxWidth(), icon = PopIcons.Close)
}

/** Corner brackets and a sweeping line over the camera. */
@Composable
private fun ScanOverlay(modifier: Modifier) {
    val sig = Pop.palette.signal
    val t = androidx.compose.animation.core.rememberInfiniteTransition(label = "scan")
    val p by t.animateFloat(
        0f, 1f,
        androidx.compose.animation.core.infiniteRepeatable(tween(2200, easing = FastOutSlowInEasing), androidx.compose.animation.core.RepeatMode.Reverse),
        label = "line",
    )
    Canvas(modifier) {
        val m = size.minDimension * 0.16f
        val l = size.minDimension * 0.12f
        val w = 4.dp.toPx()
        val x0 = m; val y0 = m; val x1 = size.width - m; val y1 = size.height - m
        fun corner(x: Float, y: Float, dx: Float, dy: Float) {
            drawLine(Color.White, Offset(x, y), Offset(x + dx * l, y), w, StrokeCap.Round)
            drawLine(Color.White, Offset(x, y), Offset(x, y + dy * l), w, StrokeCap.Round)
        }
        corner(x0, y0, 1f, 1f); corner(x1, y0, -1f, 1f); corner(x0, y1, 1f, -1f); corner(x1, y1, -1f, -1f)
        val y = y0 + (y1 - y0) * p
        drawLine(
            Brush.horizontalGradient(listOf(Color.Transparent, sig, Color.Transparent), x0, x1),
            Offset(x0 + w, y), Offset(x1 - w, y), 2.dp.toPx(),
        )
    }
}

@Composable
private fun Confirm(s: UiState, c: PopController) {
    val v = s.session
    val p = v?.partner
    PageTitle("Is this them?", "Check that the name and model match the phone next to you.")
    if (v == null || p == null) {
        Panel {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(12.dp))
                Text("No partner yet", style = MaterialTheme.typography.bodyLarge, color = Pop.palette.muted)
            }
        }
    } else {
        Reveal {
            Panel(padding = androidx.compose.foundation.layout.PaddingValues(22.dp)) {
                Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Avatar(p.display_name ?: "?", size = 84.dp)
                    Spacer(Modifier.height(4.dp))
                    Text(p.display_name ?: "(no name)", style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
                    Text(p.model ?: "Unknown model", style = MaterialTheme.typography.bodyLarge, color = Pop.palette.muted, textAlign = TextAlign.Center)
                    if (p.attested) Pill("Attested key", Tone.Good, icon = PopIcons.Shield) else Pill("Unattested key", Tone.Warn)
                }
                Hairline()
                Field("device", p.device_id)
            }
        }
        val mine = v.role ?: s.role
        val other = if (mine == "A") "B" else "A"
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally)) {
            Pill(if (s.role == "A") "You are host (A)" else "You are guest (B)", Tone.Neutral)
            if (v.confirmed[other] == true) Pill("Partner confirmed", Tone.Good, icon = PopIcons.Check)
            else Pill("Partner deciding", Tone.Neutral, dot = true)
        }
    }
    val askMic = rememberMicPermissionRequest { c.confirmPartner() }
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        SecondaryButton("Cancel", c::abortPairing, Modifier.weight(1f))
        PrimaryButton(
            if (s.confirmSent) "Waiting…" else "Confirm", askMic, Modifier.weight(1.4f),
            enabled = !s.busy && p != null, loading = s.confirmSent, icon = PopIcons.Check,
        )
    }
}

// ---------------------------------------------------------------- run / result

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

private val phaseSteps = listOf(
    RunPhase.Arming to "Get ready",
    RunPhase.Running to "Play and listen",
    RunPhase.SelfCheck to "Hear own sound",
    RunPhase.Committing to "Lock in recording",
    RunPhase.Measuring to "Measure distance",
    RunPhase.Submitting to "Sign and send",
    RunPhase.WaitingResult to "Partner's result",
)

@Composable
private fun Run(s: UiState, c: PopController) {
    KeepScreenOn(true)
    val ph = s.runPhase
    val failing = ph == RunPhase.Failing
    PageTitle("Measuring", "Keep both phones side by side, speakers free, and stay quiet for a few seconds.")
    Box(Modifier.fillMaxWidth().height(210.dp), contentAlignment = Alignment.Center) {
        if (ph != null) PulseRings(
            Modifier.fillMaxSize(), color = if (failing) Pop.palette.bad else Pop.palette.signal,
            periodMs = if (ph == RunPhase.Running) 1400 else 2600,
        )
        Box(
            Modifier.size(92.dp).clip(CircleShape).background(Pop.palette.panel).border(1.dp, Pop.palette.hairline, CircleShape),
            contentAlignment = Alignment.Center,
        ) { PopMark(54.dp, if (failing) Pop.palette.bad else Pop.palette.signal) }
    }
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            when {
                ph != null -> phaseText[ph] ?: ph.name
                s.runBlocked != null -> "Not started"
                else -> "Preparing…"
            },
            style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center,
            color = if (failing) Pop.palette.bad else MaterialTheme.colorScheme.onSurface,
        )
        if (ph != null && s.runAttempt > 0) Pill("Second try (attempt ${s.runAttempt})", Tone.Warn)
    }
    s.runNote?.let { Banner(it, Tone.Warn) }
    s.runBlocked?.let { msg ->
        val pre = s.preflight
        val askMic = rememberMicPermissionRequest { c.refreshPreflight() }
        Banner(msg, Tone.Bad, title = "Can't start yet") {
            if (pre != null && !pre.micPermission) SecondaryButton("Allow mic", askMic, icon = PopIcons.Mic, compact = true)
            if (pre != null && pre.volumeFrac < 0.6) SecondaryButton("Raise volume", c::raiseVolume, icon = PopIcons.Volume, compact = true)
        }
        PrimaryButton("Start", c::startRun, Modifier.fillMaxWidth(), enabled = !s.busy)
    }
    if (ph != null || s.runBlocked == null) Panel(spacing = 0.dp) { PhaseTimeline(ph) }
    s.preflight?.warnings?.takeIf { it.isNotEmpty() }?.let { Banner(it.joinToString("\n"), Tone.Warn, title = "Heads up") }
    SecondaryButton("Cancel", c::abortRun, Modifier.fillMaxWidth(), icon = PopIcons.Close)
}

@Composable
private fun ColumnScope.PhaseTimeline(current: RunPhase?) {
    val pal = Pop.palette
    val failing = current == RunPhase.Failing
    val curIdx = phaseSteps.indexOfFirst { it.first == current }
    for ((i, step) in phaseSteps.withIndex()) {
        val done = curIdx >= 0 && i < curIdx
        val now = i == curIdx
        Row(Modifier.fillMaxWidth().height(40.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.width(28.dp).fillMaxSize(), contentAlignment = Alignment.Center) {
                // connector
                Canvas(Modifier.fillMaxSize()) {
                    val x = size.width / 2
                    if (i > 0) drawLine(if (done || now) pal.signal.copy(alpha = 0.6f) else pal.hairline, Offset(x, 0f), Offset(x, size.height / 2 - 10.dp.toPx()), 2.dp.toPx())
                    if (i < phaseSteps.lastIndex) drawLine(if (done) pal.signal.copy(alpha = 0.6f) else pal.hairline, Offset(x, size.height / 2 + 10.dp.toPx()), Offset(x, size.height), 2.dp.toPx())
                }
                when {
                    done -> Box(Modifier.size(20.dp).clip(CircleShape).background(pal.signal), contentAlignment = Alignment.Center) {
                        Icon(PopIcons.Check, null, Modifier.size(13.dp), tint = MaterialTheme.colorScheme.onPrimary)
                    }
                    now -> Box(Modifier.size(20.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(Modifier.size(20.dp), color = pal.signal, strokeWidth = 2.dp)
                        Box(Modifier.size(7.dp).clip(CircleShape).background(pal.signal))
                    }
                    else -> Box(Modifier.size(12.dp).clip(CircleShape).border(2.dp, pal.hairline, CircleShape))
                }
            }
            Spacer(Modifier.width(12.dp))
            Text(
                step.second,
                style = if (now) MaterialTheme.typography.titleSmall else MaterialTheme.typography.bodyMedium,
                color = when {
                    now -> MaterialTheme.colorScheme.onSurface
                    done -> pal.muted
                    else -> pal.muted.copy(alpha = 0.6f)
                },
            )
        }
    }
    if (failing) {
        Spacer(Modifier.height(8.dp))
        Pill("Measurement failed", Tone.Bad, icon = PopIcons.Alert)
    }
}

@Composable
private fun Result(s: UiState, c: PopController) {
    val r = s.result
    KeepScreenOn(false)
    if (r == null) {
        Panel { Text("No result", style = MaterialTheme.typography.bodyLarge, color = Pop.palette.muted) }
    } else {
        val near = r.verdict == "NEAR"
        Panel(padding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 12.dp)) {
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                VerdictBadge(near, size = 120.dp)
                Text(
                    if (near) "Near" else "Not near", style = MaterialTheme.typography.displayMedium,
                    color = if (near) Pop.palette.good else Pop.palette.bad,
                )
                (r.user_text ?: Reasons.of(r.reason))?.let {
                    Text(it, style = MaterialTheme.typography.bodyLarge, color = Pop.palette.muted, textAlign = TextAlign.Center)
                }
            }
            r.flight_cm?.let { cm ->
                Reveal(400) {
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 10.dp, bottom = 6.dp)) {
                        Hairline()
                        Row(verticalAlignment = Alignment.Bottom) {
                            Text(fmt1(cm), style = MaterialTheme.typography.headlineLarge)
                            Text(" cm", style = MaterialTheme.typography.titleMedium, color = Pop.palette.muted, modifier = Modifier.padding(bottom = 4.dp))
                            Spacer(Modifier.weight(1f))
                            Text("time of flight", style = MaterialTheme.typography.labelMedium, color = Pop.palette.muted, modifier = Modifier.padding(bottom = 6.dp))
                        }
                        DistanceMeter(cm, PopConstants.NEAR_CM)
                    }
                }
            }
        }
        Reveal(250) {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                s.proof?.let { ProofCard("Option A proof", it, onRetry = c::proveNow) }
                Panel {
                    Expandable("Details", subtitle = r.reason ?: r.session_id?.let { "session ${it.take(12)}…" }, icon = PopIcons.Info, initiallyOpen = !near) {
                        r.reason?.let { Field("reason", it) }
                        s.resultDetail?.let { Field("detail", it) }
                        if (r.attempts.isNotEmpty()) Field("attempts", r.attempts.joinToString("\n") { a ->
                            listOf("attempt", "outcome", "reason", "by").mapNotNull { k -> a[k]?.toString()?.trim('"')?.takeIf { it != "null" } }.joinToString(" ")
                        })
                        r.session_id?.let { Field("session", it) }
                    }
                }
            }
        }
    }
    PrimaryButton("Done", c::again, Modifier.fillMaxWidth())
}

@Composable
private fun ProofCard(title: String, p: ProofStatus, onRetry: (() -> Unit)?) {
    Panel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconTile(PopIcons.Shield, when (p) {
                is ProofStatus.Done -> Tone.Good
                is ProofStatus.Failed -> Tone.Bad
                is ProofStatus.NeedKey -> Tone.Warn
                else -> Tone.Accent
            })
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleSmall)
                Text(
                    when (p) {
                        is ProofStatus.Skipped -> "Skipped"
                        is ProofStatus.NeedKey -> "Needs proving key"
                        is ProofStatus.Downloading -> "Downloading key"
                        is ProofStatus.Step -> "Working"
                        is ProofStatus.Done -> "Proved"
                        is ProofStatus.Failed -> "Failed"
                    },
                    style = MaterialTheme.typography.bodySmall, color = Pop.palette.muted,
                )
            }
            when (p) {
                is ProofStatus.Done -> Pill("Proved", Tone.Good, icon = PopIcons.Check)
                is ProofStatus.Failed -> Pill("Failed", Tone.Bad)
                is ProofStatus.Step, is ProofStatus.Downloading -> CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                else -> {}
            }
        }
        when (p) {
            is ProofStatus.Skipped -> Text(p.why, style = MaterialTheme.typography.bodyMedium, color = Pop.palette.muted)
            is ProofStatus.NeedKey -> {
                Text("Proving key ${p.circuit} needed (${ProofStats.mb(p.bytes)}). You are on mobile data; Wi-Fi recommended.", style = MaterialTheme.typography.bodyMedium)
                if (onRetry != null) SecondaryButton("Download and prove", onRetry, Modifier.fillMaxWidth(), compact = true)
            }
            is ProofStatus.Downloading -> {
                Text("Downloading proving key ${ProofStats.mb(p.done)} / ${ProofStats.mb(p.total)} (Wi-Fi recommended)", style = MaterialTheme.typography.bodyMedium)
                LinearProgressIndicator(
                    progress = { if (p.total > 0) (p.done.toFloat() / p.total).coerceIn(0f, 1f) else 0f },
                    modifier = Modifier.fillMaxWidth().height(6.dp).clip(CircleShape),
                    trackColor = MaterialTheme.colorScheme.surfaceContainerHighest, drawStopIndicator = {},
                )
            }
            is ProofStatus.Step -> {
                Text(p.name.replaceFirstChar { it.uppercase() } + "…", style = MaterialTheme.typography.bodyMedium)
                LinearProgressIndicator(Modifier.fillMaxWidth().height(6.dp).clip(CircleShape), trackColor = MaterialTheme.colorScheme.surfaceContainerHighest)
            }
            is ProofStatus.Done -> {
                p.upload?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
                CodeBlock(p.stats.lines().joinToString("\n"))
            }
            is ProofStatus.Failed -> {
                Text("Failed (${p.step}): ${p.why}", style = MaterialTheme.typography.bodyMedium, color = Pop.palette.bad)
                if (onRetry != null) SecondaryButton("Retry", onRetry, Modifier.fillMaxWidth(), icon = PopIcons.Refresh, compact = true)
            }
        }
    }
}

// ---------------------------------------------------------------- tools

private val modeLabel = mapOf("measurement" to "Measurement", "default" to "Default", "videoRecording" to "Video")

@Composable
private fun AudioCheck(s: UiState, c: PopController) {
    KeepScreenOn(s.audioCheckRunning)
    val busy = s.audioCheckRunning
    PageTitle(
        "Audio check",
        "Plays a test sound like the real one through the same audio path, records it and measures how loud " +
            "this phone hears itself. Quiet room, phone on the table, speaker uncovered.",
    )
    if (s.audioModes.isNotEmpty()) {
        Panel {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("Session mode", style = MaterialTheme.typography.titleSmall)
                Text("Voice processing off; also used for runs", style = MaterialTheme.typography.bodySmall, color = Pop.palette.muted)
            }
            Segmented(s.audioModes.map { it to (modeLabel[it] ?: it) }, s.audioMode, { c.setAudioMode(it) }, enabled = !busy)
            Hairline()
            SwitchRow("Force speaker", "Check only; runs always use the speaker", s.forceSpeaker, { c.setForceSpeaker(it) }, enabled = !busy)
        }
    }
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text("Tune boost", style = MaterialTheme.typography.titleSmall)
            Text("Check only · server tune_db ${s.serverTuneDb?.let { f1(it) } ?: "?"} dB", style = MaterialTheme.typography.bodySmall, color = Pop.palette.muted)
        }
        Segmented(
            TuneBoost.STEPS_DB.map { d -> d.toString() to (if (d == 0.0) "0 dB" else "+${d.toInt()} dB") },
            s.tuneDb.toString(), { k -> k.toDoubleOrNull()?.let { c.setTuneDb(it) } }, enabled = !busy,
        )
        s.audioRoute?.let { r -> if (s.audioCheck == null) FactRow("Output now", routeText(r)) }
    }
    val askMic = rememberMicPermissionRequest { if (it) c.audioCheck() }
    PrimaryButton(if (busy) "Playing…" else "Run check", askMic, Modifier.fillMaxWidth(), enabled = !s.busy, loading = busy, icon = PopIcons.Speaker)
    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth().height(4.dp).clip(CircleShape), trackColor = MaterialTheme.colorScheme.surfaceContainerHighest)
    s.audioCheck?.let { r ->
        val lv = r.levels
        val tone = when {
            r.pass -> Tone.Good
            r.route.isSpeaker && lv.verdict == "weak" -> Tone.Warn
            else -> Tone.Bad
        }
        Reveal {
            Panel {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconTile(if (r.pass) PopIcons.Check else PopIcons.Alert, tone, size = 46.dp)
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(r.verdict, style = MaterialTheme.typography.headlineMedium, color = com.enconomy.pop.ui.toneColor(tone))
                        Text("Self-hearing level", style = MaterialTheme.typography.bodySmall, color = Pop.palette.muted)
                    }
                }
                MarginBar("2–18 kHz margin (needs ${SelfHear.OK_MARGIN_DB.toInt()} dB)", lv.highMarginDb, SelfHear.OK_MARGIN_DB, SelfHear.WEAK_MARGIN_DB)
                Hairline()
                FactRow("Route", routeText(r.route))
                FactRow("Volume", "${kotlin.math.round(r.route.volume * 100).toInt()}%")
                FactRow("Mode", r.route.mode)
                FactRow("Sample rate", "${r.route.sampleRate} Hz")
                FactRow("Latency", "${r.latencyMs?.let { f1(it) } ?: "?"} ms, ts ${r.tsSource}")
                FactRow("Tune boost", "+${f1(r.tuneRequestedDb)} asked, +${f1(r.tuneAppliedDb)} dB applied")
                FactRow("Play peak", "${f1(r.playPeak * 100)}% (${f1(20 * kotlin.math.log10(r.playPeak))} dBFS)")
                if (r.route.detail.isNotEmpty()) Field("detail", r.route.detail)
                Expandable("Raw levels") {
                    CodeBlock(
                        "band          self    floor   margin\n" +
                            "200-1600 Hz ${pad(lv.lowDb)} ${pad(lv.floorLowDb)} ${pad(lv.lowMarginDb)}\n" +
                            "2-18 kHz    ${pad(lv.highDb)} ${pad(lv.floorHighDb)} ${pad(lv.highMarginDb)}\n" +
                            "peak        ${lv.peak} (${f1(lv.peakDb)} dBFS), floor ${lv.floorPeak}\n" +
                            "dBFS; OK needs 2-18 kHz margin >= ${SelfHear.OK_MARGIN_DB.toInt()} dB",
                    )
                }
            }
        }
        if (r.warnings.isNotEmpty()) Banner(r.warnings.joinToString("\n"), Tone.Warn, title = "Warnings")
    }
}

private fun routeText(r: AudioRoute) = r.output + (if (r.outputName.isNotBlank()) " (${r.outputName})" else "")

private fun f1(x: Double) = (kotlin.math.round(x * 10) / 10).toString()

private fun pad(x: Double) = f1(x).padStart(7)

@Composable
private fun Bench(s: UiState, c: PopController) {
    PageTitle(
        "Prover bench",
        "Proves a bundled field fixture on this phone: witness input, key load, constraint check, proof. " +
            "Needs about 2 GB of RAM and the proving key (downloaded once, Wi-Fi recommended).",
    )
    val running = s.benchStatus is ProofStatus.Step || s.benchStatus is ProofStatus.Downloading
    Panel {
        val err = ProverLib.loadError
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconTile(PopIcons.Chip, if (err == null) Tone.Accent else Tone.Bad)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text("Native prover", style = MaterialTheme.typography.titleSmall)
                Text(err ?: ProverLib.version(), style = Pop.mono, color = if (err == null) Pop.palette.muted else Pop.palette.bad)
            }
        }
    }
    SectionLabel("Proving keys")
    Panel {
        for ((i, k) in ProvingKeys.all.withIndex()) {
            if (i > 0) Hairline()
            val st = s.keyState[k.circuit] ?: "?"
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(k.circuit, style = Pop.mono.copy(fontWeight = FontWeight.SemiBold))
                    Text("${k.sampleRate} Hz", style = MaterialTheme.typography.bodySmall, color = Pop.palette.muted)
                }
                Pill(st, when {
                    st == "present" -> Tone.Good
                    st.startsWith("partial") -> Tone.Warn
                    else -> Tone.Neutral
                }, dot = true)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                SecondaryButton("Download", { c.benchDownload(k) }, enabled = !running, compact = true)
                QuietButton("Delete", { c.benchDeleteKey(k) }, enabled = !running, tone = Tone.Bad)
            }
        }
    }
    SectionLabel("Fixtures")
    Panel {
        for ((i, n) in BenchFixture.NAMES.withIndex()) {
            if (i > 0) Hairline()
            Text(n, style = Pop.mono.copy(fontWeight = FontWeight.SemiBold))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                PrimaryButton("Prove", { c.benchRun(n) }, enabled = !running && !s.proofBusy)
                QuietButton("Ignore RAM check", { c.benchRun(n, force = true) }, enabled = !running && !s.proofBusy, tone = Tone.Neutral)
            }
        }
    }
    s.benchStatus?.let { ProofCard("Status", it, onRetry = null) }
    if (s.benchLog.isNotEmpty()) CodeBlock(s.benchLog.joinToString("\n"))
}
