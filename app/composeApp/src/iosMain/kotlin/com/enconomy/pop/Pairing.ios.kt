@file:OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)

package com.enconomy.pop

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.viewinterop.UIKitView
import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.CValue
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.readValue
import kotlinx.cinterop.useContents
import kotlinx.cinterop.usePinned
import platform.AVFoundation.AVAuthorizationStatusAuthorized
import platform.AVFoundation.AVAuthorizationStatusNotDetermined
import platform.AVFoundation.AVCaptureConnection
import platform.AVFoundation.AVCaptureDevice
import platform.AVFoundation.AVCaptureDeviceInput
import platform.AVFoundation.AVCaptureMetadataOutput
import platform.AVFoundation.AVCaptureMetadataOutputObjectsDelegateProtocol
import platform.AVFoundation.AVCaptureOutput
import platform.AVFoundation.AVCaptureSession
import platform.AVFoundation.AVCaptureVideoPreviewLayer
import platform.AVFoundation.AVLayerVideoGravityResizeAspectFill
import platform.AVFoundation.AVMediaTypeVideo
import platform.AVFoundation.AVMetadataMachineReadableCodeObject
import platform.AVFoundation.AVMetadataObjectTypeQRCode
import platform.AVFoundation.authorizationStatusForMediaType
import platform.AVFoundation.requestAccessForMediaType
import platform.CoreGraphics.CGRect
import platform.CoreGraphics.CGRectZero
import platform.CoreImage.CIContext
import platform.CoreImage.CIFilter
import platform.CoreImage.filterWithName
import platform.CoreImage.kCIFormatRGBA8
import platform.CoreNFC.NFCISO7816APDU
import platform.CoreNFC.NFCPollingISO14443
import platform.CoreNFC.NFCReaderSessionInvalidationErrorFirstNDEFTagRead
import platform.CoreNFC.NFCReaderSessionInvalidationErrorSessionTimeout
import platform.CoreNFC.NFCReaderSessionInvalidationErrorUserCanceled
import platform.CoreNFC.NFCTagProtocol
import platform.CoreNFC.NFCTagReaderSession
import platform.CoreNFC.NFCTagReaderSessionDelegateProtocol
import platform.Foundation.NSBundle
import platform.Foundation.NSData
import platform.Foundation.NSError
import platform.Foundation.NSLog
import platform.Foundation.NSURL
import platform.Foundation.create
import platform.Foundation.setValue
import platform.QuartzCore.CATransaction
import platform.UIKit.UIApplication
import platform.UIKit.UIApplicationOpenSettingsURLString
import platform.UIKit.UIColor
import platform.UIKit.UIView
import platform.darwin.NSObject
import platform.darwin.dispatch_async
import platform.darwin.dispatch_get_main_queue
import platform.darwin.dispatch_queue_create
import platform.posix.memcpy

/** No HCE on iOS: nothing reads the beacon; host pairs by QR. */
actual object InviteBeacon {
    private var bytes: ByteArray? = null
    actual fun publish(invite: ByteArray?) { bytes = invite?.copyOf() }
    actual fun current(): ByteArray? = bytes
}

/** Info.plist PopNfcReader = $(POP_NFC_READER): YES only in the paid build (entitlement present). */
internal fun nfcReaderEnabled(): Boolean =
    (NSBundle.mainBundle.objectForInfoDictionaryKey("PopNfcReader") as? String) == "YES"

/** Reader only; iOS has no NFC switch, so never Off. Free-team builds report Unsupported (QR only). */
@Composable
actual fun rememberNfcState(): NfcState =
    remember { if (nfcReaderEnabled() && NFCTagReaderSession.readingAvailable) NfcState.On else NfcState.Unsupported }

actual fun nfcCanHost(): Boolean = false

actual fun openNfcSettings() = openAppSettings()

private fun openAppSettings() {
    NSURL.URLWithString(UIApplicationOpenSettingsURLString)?.let {
        UIApplication.sharedApplication.openURL(it, emptyMap<Any?, Any>(), null)
    }
}

@Composable
actual fun HceForeground() {}

private fun ByteArray.popNsData(): NSData = usePinned { NSData.create(bytes = it.addressOf(0), length = size.toULong()) }

private fun NSData.popBytes(): ByteArray {
    val n = length.toInt()
    val out = ByteArray(n)
    if (n > 0) out.usePinned { memcpy(it.addressOf(0), bytes, length) }
    return out
}

/**
 * Core NFC shows a system sheet, so unlike Android we don't poll while composed: the button starts
 * one session (60 s). Reads the Android host's HCE card: SELECT(AID) -> 49 bytes || 9000.
 */
@Composable
actual fun NfcInviteReader(onInvite: (ByteArray) -> Unit, onError: (String) -> Unit) {
    val ok by rememberUpdatedState(onInvite)
    val err by rememberUpdatedState(onError)
    val reader = remember { NfcReader({ ok(it) }, { err(it) }) }
    DisposableEffect(reader) { onDispose { reader.stop() } }
    OutlinedButton(onClick = reader::start) { Text("Tap with NFC") }
}

/** Delegate + session holder. Session queue is main, so every callback runs on main. */
private class NfcReader(
    private val onInvite: (ByteArray) -> Unit,
    private val onError: (String) -> Unit,
) : NSObject(), NFCTagReaderSessionDelegateProtocol {
    private var session: NFCTagReaderSession? = null
    private var disposed = false

    fun start() {
        if (disposed || session != null) return
        if (!NFCTagReaderSession.readingAvailable) { onError("nfc_unavailable"); return }
        val s = NFCTagReaderSession(pollingOption = NFCPollingISO14443, delegate = this, queue = dispatch_get_main_queue())
        s.alertMessage = "Hold the top of this iPhone to the back of the host phone."
        session = s
        s.beginSession()
    }

    fun stop() {
        disposed = true
        session?.invalidateSession()
        session = null
    }

    override fun tagReaderSessionDidBecomeActive(session: NFCTagReaderSession) {}

    override fun tagReaderSession(session: NFCTagReaderSession, didInvalidateWithError: NSError) {
        if (this.session === session) this.session = null
        if (disposed) return
        when (didInvalidateWithError.code) {
            NFCReaderSessionInvalidationErrorUserCanceled, NFCReaderSessionInvalidationErrorFirstNDEFTagRead -> {}
            NFCReaderSessionInvalidationErrorSessionTimeout -> onError("nfc_timeout")
            else -> {
                NSLog("pop nfc invalidated: %@", didInvalidateWithError.localizedDescription)
                onError("nfc_session_${didInvalidateWithError.code}")
            }
        }
    }

    override fun tagReaderSession(session: NFCTagReaderSession, didDetectTags: List<*>) {
        if (didDetectTags.size > 1) {
            session.alertMessage = "More than one tag. Hold only the host phone."
            session.restartPolling()
            return
        }
        val tag = didDetectTags.firstOrNull() as? NFCTagProtocol ?: return
        val iso = tag.asNFCISO7816Tag()
        if (iso == null) {
            retry(session, "Not a pop host. Hold the host phone.")
            return
        }
        session.connectToTag(tag) { cerr ->
            dispatch_async(dispatch_get_main_queue()) {
                if (cerr != null) {
                    fail(session, "nfc_read_failed", "Lost the host. Try again.")
                    return@dispatch_async
                }
                val apdu = NFCISO7816APDU(data = PopApdu.SELECT.popNsData())
                iso.sendCommandAPDU(apdu) { data, sw1, sw2, aerr ->
                    dispatch_async(dispatch_get_main_queue()) { onResponse(session, data, sw1, sw2, aerr) }
                }
            }
        }
    }

    private fun onResponse(session: NFCTagReaderSession, data: NSData?, sw1: UByte, sw2: UByte, aerr: NSError?) {
        if (aerr != null) {
            NSLog("pop nfc apdu: %@", aerr.localizedDescription)
            fail(session, "nfc_read_failed", "Read failed. Try again.")
            return
        }
        val resp = (data?.popBytes() ?: ByteArray(0)) + byteArrayOf(sw1.toByte(), sw2.toByte())
        val b = try {
            PopApdu.parseResponse(resp)
        } catch (e: InviteException) {
            // Host not ready yet: keep the sheet up, like Android's reader mode.
            if (e.code == "nfc_no_invite") retry(session, "Host has no invite yet. Tap again.")
            else fail(session, e.code, e.message ?: "Bad response.")
            return
        }
        session.alertMessage = "Invite read."
        session.invalidateSession()
        if (!disposed) onInvite(b)
    }

    private fun retry(session: NFCTagReaderSession, msg: String) {
        session.alertMessage = msg
        session.restartPolling()
    }

    private fun fail(session: NFCTagReaderSession, code: String, msg: String) {
        session.invalidateSessionWithErrorMessage(msg)
        if (!disposed) onError(code)
    }
}

@Composable
actual fun QrCode(text: String, modifier: Modifier) {
    val m = remember(text) { qrMatrix(text) }
    if (m == null) {
        Box(modifier) { Text(text) }
        return
    }
    Canvas(modifier) {
        drawRect(Color.White)
        val cell = minOf(size.width, size.height) / m.n
        val x0 = (size.width - cell * m.n) / 2
        val y0 = (size.height - cell * m.n) / 2
        for (y in 0 until m.n) for (x in 0 until m.n) {
            if (m.dark[y * m.n + x]) drawRect(Color.Black, Offset(x0 + x * cell, y0 + y * cell), Size(cell + 0.5f, cell + 0.5f))
        }
    }
}

internal class QrMatrix(val n: Int, val dark: BooleanArray)

/**
 * CIQRCodeGenerator, EC level M, 1 px per module; cropped to the symbol and re-padded with quiet zone 2.
 * RGBA8: CI never writes R8/L8 bitmaps. Row 0 is the top.
 */
internal fun qrMatrix(text: String): QrMatrix? {
    val f = CIFilter.filterWithName("CIQRCodeGenerator") ?: return null
    f.setValue(text.encodeToByteArray().popNsData(), forKey = "inputMessage")
    f.setValue("M", forKey = "inputCorrectionLevel")
    val img = f.outputImage ?: return null
    val ext: CValue<CGRect> = img.extent
    val w = ext.useContents { size.width.toInt() }
    val h = ext.useContents { size.height.toInt() }
    if (w <= 0 || h <= 0) return null
    val rgba = ByteArray(4 * w * h)
    rgba.usePinned { CIContext.contextWithOptions(null).render(img, it.addressOf(0), 4L * w, ext, kCIFormatRGBA8, null) }
    val px = ByteArray(w * h) { rgba[4 * it] }
    var x0 = w; var y0 = h; var x1 = -1; var y1 = -1
    for (y in 0 until h) for (x in 0 until w) {
        if ((px[y * w + x].toInt() and 0xff) < 128) {
            if (x < x0) x0 = x; if (x > x1) x1 = x
            if (y < y0) y0 = y; if (y > y1) y1 = y
        }
    }
    if (x1 < 0) return null
    val side = maxOf(x1 - x0, y1 - y0) + 1
    val q = 2
    val n = side + 2 * q
    val dark = BooleanArray(n * n)
    for (y in 0 until side) for (x in 0 until side) {
        val sx = x0 + x
        val sy = y0 + y
        if (sx < w && sy < h && (px[sy * w + sx].toInt() and 0xff) < 128) dark[(y + q) * n + x + q] = true
    }
    return QrMatrix(n, dark)
}

private enum class Cam { Unknown, Asking, Granted, Denied }

private fun camStatus(): Cam = when (AVCaptureDevice.authorizationStatusForMediaType(AVMediaTypeVideo)) {
    AVAuthorizationStatusAuthorized -> Cam.Granted
    AVAuthorizationStatusNotDetermined -> Cam.Unknown
    else -> Cam.Denied
}

@Composable
actual fun QrScanner(onText: (String) -> Unit, modifier: Modifier) {
    val hasCam = remember { AVCaptureDevice.defaultDeviceWithMediaType(AVMediaTypeVideo) != null }
    if (!hasCam) {
        Text("No camera on this device.")
        return
    }
    var cam by remember { mutableStateOf(camStatus()) }
    DisposableEffect(Unit) {
        var live = true
        if (cam == Cam.Unknown) {
            cam = Cam.Asking
            AVCaptureDevice.requestAccessForMediaType(AVMediaTypeVideo) { g ->
                dispatch_async(dispatch_get_main_queue()) { if (live) cam = if (g) Cam.Granted else Cam.Denied }
            }
        }
        onDispose { live = false }
    }
    when (cam) {
        Cam.Granted -> CameraQr(onText, modifier)
        Cam.Denied -> Box(modifier) {
            Column {
                Text("Camera denied. Allow it in Settings to scan the QR.")
                Button(onClick = ::openAppSettings) { Text("Open Settings") }
            }
        }
        else -> Box(modifier) { Text("Waiting for camera permission…") }
    }
}

/** Preview view: keeps the layer sized to the view. */
private class PreviewView(val layerPreview: AVCaptureVideoPreviewLayer) : UIView(frame = CGRectZero.readValue()) {
    init {
        backgroundColor = UIColor.blackColor
        layer.addSublayer(layerPreview)
    }

    override fun layoutSubviews() {
        super.layoutSubviews()
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        layerPreview.setFrame(bounds)
        CATransaction.commit()
    }
}

/** Metadata delegate; called on main (queue passed below). */
private class QrDelegate(val onText: (String) -> Unit) : NSObject(), AVCaptureMetadataOutputObjectsDelegateProtocol {
    var live = true

    override fun captureOutput(output: AVCaptureOutput, didOutputMetadataObjects: List<*>, fromConnection: AVCaptureConnection) {
        if (!live) return
        didOutputMetadataObjects.firstNotNullOfOrNull { (it as? AVMetadataMachineReadableCodeObject)?.stringValue }?.let(onText)
    }
}

@Composable
private fun CameraQr(onText: (String) -> Unit, modifier: Modifier) {
    val cb by rememberUpdatedState(onText)
    val session = remember { AVCaptureSession() }
    val delegate = remember { QrDelegate { cb(it) } }
    val queue = remember { dispatch_queue_create("pop.qr", null) }
    val view = remember {
        PreviewView(AVCaptureVideoPreviewLayer(session = session).apply { videoGravity = AVLayerVideoGravityResizeAspectFill })
    }
    DisposableEffect(session) {
        val out = AVCaptureMetadataOutput()
        // Configure and start on the session queue (addInput and startRunning block).
        dispatch_async(queue) {
            val dev = AVCaptureDevice.defaultDeviceWithMediaType(AVMediaTypeVideo)
            val input = dev?.let { AVCaptureDeviceInput.deviceInputWithDevice(it, null) }
            if (input == null) {
                NSLog("pop qr: no camera input")
                return@dispatch_async
            }
            session.beginConfiguration()
            if (session.canAddInput(input)) session.addInput(input)
            if (session.canAddOutput(out)) {
                session.addOutput(out)
                out.setMetadataObjectsDelegate(delegate, dispatch_get_main_queue())
                if (out.availableMetadataObjectTypes.contains(AVMetadataObjectTypeQRCode)) {
                    out.metadataObjectTypes = listOf(AVMetadataObjectTypeQRCode)
                }
            }
            session.commitConfiguration()
            if (delegate.live) session.startRunning()
        }
        onDispose {
            delegate.live = false
            dispatch_async(queue) {
                out.setMetadataObjectsDelegate(null, null)
                session.stopRunning()
            }
        }
    }
    UIKitView(factory = { view }, modifier = modifier)
}
