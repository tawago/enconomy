package com.enconomy.pop

import androidx.compose.foundation.layout.Box
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import platform.CoreNFC.NFCTagReaderSession
import platform.Foundation.NSBundle
import platform.Foundation.NSURL
import platform.UIKit.UIApplication
import platform.UIKit.UIApplicationOpenSettingsURLString

/** No HCE on iOS: nothing reads the beacon; host pairs by QR. */
actual object InviteBeacon {
    private var bytes: ByteArray? = null
    actual fun publish(invite: ByteArray?) { bytes = invite?.copyOf() }
    actual fun current(): ByteArray? = bytes
}

/** Info.plist PopNfcReader = $(POP_NFC_READER): YES only in the paid build (entitlement present). */
internal fun nfcReaderEnabled(): Boolean =
    (NSBundle.mainBundle.objectForInfoDictionaryKey("PopNfcReader") as? String) == "YES"

/** Reader only; iOS has no NFC switch, so never Off. */
@Composable
actual fun rememberNfcState(): NfcState =
    if (nfcReaderEnabled() && NFCTagReaderSession.readingAvailable) NfcState.On else NfcState.Unsupported

actual fun nfcCanHost(): Boolean = false

actual fun openNfcSettings() {
    NSURL.URLWithString(UIApplicationOpenSettingsURLString)?.let {
        UIApplication.sharedApplication.openURL(it, emptyMap<Any?, Any>(), null)
    }
}

@Composable
actual fun HceForeground() {}

/** TODO(pairing lane): NFCTagReaderSession(.iso14443), SELECT AID F0454E434F504F50, PopApdu.parseResponse. */
@Composable
actual fun NfcInviteReader(onInvite: (ByteArray) -> Unit, onError: (String) -> Unit) {}

/** TODO(pairing lane): CIQRCodeGenerator, EC level M, quiet zone 2, nearest scaling. */
@Composable
actual fun QrCode(text: String, modifier: Modifier) {
    Box(modifier) { Text(text) }
}

/** TODO(pairing lane): AVCaptureSession + AVCaptureMetadataOutput (qr), camera permission. */
@Composable
actual fun QrScanner(onText: (String) -> Unit, modifier: Modifier) {
    Box(modifier) { Text("QR scanning not implemented on iOS yet.") }
}
