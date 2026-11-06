package com.enconomy.pop

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import kotlinx.coroutines.await

/** Web pairing: QR only (no NFC in browsers). */

actual object InviteBeacon {
    private var cur: ByteArray? = null
    actual fun publish(invite: ByteArray?) { cur = invite }
    actual fun current(): ByteArray? = cur
}

@Composable
actual fun rememberNfcState(): NfcState = NfcState.Unsupported

actual fun nfcCanHost(): Boolean = false

actual fun openNfcSettings() {}

@Composable
actual fun HceForeground() {}

@Composable
actual fun NfcInviteReader(onInvite: (ByteArray) -> Unit, onError: (String) -> Unit) {}

private fun qrMake(g: JsAny, text: String): JsAny = js("(function(){ const q = g; q.addData(text, 'Byte'); q.make(); return q; })()")
private fun qrCount(q: JsAny): Int = js("q.getModuleCount()")
private fun qrDark(q: JsAny, r: Int, c: Int): Boolean = js("q.isDark(r, c)")

/** Module matrix of [text] (auto version, EC level M). */
private fun qrMatrix(text: String): Array<BooleanArray>? = runCatching {
    val q = qrMake(qrcode(0, "M"), text)
    val n = qrCount(q)
    Array(n) { r -> BooleanArray(n) { c -> qrDark(q, r, c) } }
}.getOrNull()

@Composable
actual fun QrCode(text: String, modifier: Modifier) {
    val m = remember(text) { qrMatrix(text) }
    if (m == null) {
        Box(modifier, contentAlignment = Alignment.Center) { Text("QR failed") }
        return
    }
    Canvas(modifier.background(Color.White)) {
        val quiet = 2
        val n = m.size + 2 * quiet
        val cell = minOf(size.width, size.height) / n
        val ox = (size.width - cell * n) / 2
        val oy = (size.height - cell * n) / 2
        for (r in m.indices) for (c in m.indices) if (m[r][c]) {
            drawRect(Color.Black, Offset(ox + (c + quiet) * cell, oy + (r + quiet) * cell), Size(cell + 0.5f, cell + 0.5f))
        }
    }
}

/**
 * Opens the DOM camera overlay (pop-qr.js: BarcodeDetector, else jsQR, plus a paste field) while composed.
 * Each decoded text goes to [onText]; the overlay reopens until this leaves composition.
 */
@Composable
actual fun QrScanner(onText: (String) -> Unit, modifier: Modifier) {
    val cb = rememberUpdatedState(onText)
    var gen by remember { mutableStateOf(0) }
    LaunchedEffect(gen) {
        qrSetDecoder(jsQrFn())
        while (true) {
            val t = jsStr(runCatching { qrScan().await<JsAny?>() }.getOrNull()) ?: break
            cb.value(t)
        }
    }
    DisposableEffect(Unit) { onDispose { qrClose() } }
    Box(modifier.clickable { qrClose(); gen++ }, contentAlignment = Alignment.Center) {
        Text("Scanning in the camera overlay. Tap here to reopen it.")
    }
}

private fun jsQrRef(f: (JsAny, Int, Int) -> JsAny?): JsAny = js("(d, w, h) => f(d, w, h)")
private fun jsQrFn(): JsAny = jsQrRef { d, w, h -> jsQR(d, w, h) }
