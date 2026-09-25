package com.enconomy.pop

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/** Pairing transports (§3.2). Android: HCE + reader mode, ZXing render, CameraX + ML Kit scan. */

enum class NfcState { Unsupported, Off, On }

/** Card side: bytes the HCE service answers SELECT with. null = 6A 82. */
expect object InviteBeacon {
    fun publish(invite: ByteArray?)
    fun current(): ByteArray?
}

/** NFC state, refreshed on resume (user may toggle NFC in settings). */
@Composable
expect fun rememberNfcState(): NfcState

/** Opens the system NFC settings. */
expect fun openNfcSettings()

/** Host: while composed, prefer our HCE service so the tap goes to it. */
@Composable
expect fun HceForeground()

/** Guest: reader mode while composed. [onInvite] gets the 49 raw bytes; [onError] a short reason. */
@Composable
expect fun NfcInviteReader(onInvite: (ByteArray) -> Unit, onError: (String) -> Unit)

@Composable
expect fun QrCode(text: String, modifier: Modifier = Modifier)

/** Camera preview + QR decode. Asks for CAMERA itself. [onText] per decoded QR (dedupe upstream). */
@Composable
expect fun QrScanner(onText: (String) -> Unit, modifier: Modifier = Modifier)
