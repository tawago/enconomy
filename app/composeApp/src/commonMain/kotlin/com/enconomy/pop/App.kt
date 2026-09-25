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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

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
                when (s.screen) {
                    Screen.Enroll -> Enroll(s, c)
                    Screen.Home -> Home(s, c)
                    Screen.Host -> Host(s, c)
                    Screen.Join -> Join(s, c)
                    Screen.Confirm -> Confirm(s, c)
                    Screen.Run -> Placeholder("Run", "Arm, play, record, measure. Not wired yet.", c)
                    Screen.Result -> Placeholder("Result", "NEAR / NOT_NEAR + flight_cm. Not wired yet.", c)
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
    Text("Creates a hardware P-256 key (StrongBox if present) and registers it with the server.", fontSize = 13.sp)
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
}

@Composable
private fun Host(s: UiState, c: PopController) {
    Text("Host", fontWeight = FontWeight.Medium)
    val nfc = rememberNfcState()
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
        Button(onClick = c::confirmPartner, enabled = !s.busy && !s.confirmSent && p != null) {
            Text(if (s.confirmSent) "Waiting…" else "Confirm")
        }
    }
}

@Composable
private fun Placeholder(title: String, text: String, c: PopController) {
    Text(title, fontWeight = FontWeight.Medium)
    Text(text, fontSize = 13.sp)
    OutlinedButton(onClick = { c.go(Screen.Home) }) { Text("Back") }
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
