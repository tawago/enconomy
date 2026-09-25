package com.enconomy.pop

import android.Manifest
import android.app.Activity
import android.content.ComponentName
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.nfc.NfcAdapter
import android.nfc.cardemulation.CardEmulation
import android.nfc.tech.IsoDep
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.OptIn
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import java.util.concurrent.Executors

private const val TAG = "PopPairing"

actual object InviteBeacon {
    @Volatile private var bytes: ByteArray? = null
    actual fun publish(invite: ByteArray?) { bytes = invite?.copyOf() }
    actual fun current(): ByteArray? = bytes
}

private tailrec fun Context.activity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.activity()
    else -> null
}

private fun nfcStateOf(ctx: Context): NfcState {
    val a = NfcAdapter.getDefaultAdapter(ctx) ?: return NfcState.Unsupported
    return if (a.isEnabled) NfcState.On else NfcState.Off
}

/** Runs [block] on every ON_RESUME of the hosting activity (and once now). */
@Composable
private fun OnResume(block: () -> Unit) {
    val ctx = LocalContext.current
    val cb by rememberUpdatedState(block)
    DisposableEffect(ctx) {
        val owner = ctx.activity() as? LifecycleOwner
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) cb() }
        owner?.lifecycle?.addObserver(obs)
        onDispose { owner?.lifecycle?.removeObserver(obs) }
    }
}

@Composable
actual fun rememberNfcState(): NfcState {
    val ctx = LocalContext.current
    var st by remember { mutableStateOf(nfcStateOf(ctx)) }
    OnResume { st = nfcStateOf(ctx) }
    return st
}

actual fun openNfcSettings() {
    val ctx = PopApplication.instance
    val i = Intent(Settings.ACTION_NFC_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { ctx.startActivity(i) }.onFailure {
        runCatching { ctx.startActivity(Intent(Settings.ACTION_WIRELESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }
}

@Composable
actual fun HceForeground() {
    val ctx = LocalContext.current
    val act = ctx.activity() ?: return
    DisposableEffect(act) {
        val a = NfcAdapter.getDefaultAdapter(act)
        val ce = if (a != null && act.packageManager.hasSystemFeature(PackageManager.FEATURE_NFC_HOST_CARD_EMULATION)) {
            runCatching { CardEmulation.getInstance(a) }.getOrNull()
        } else null
        val cn = ComponentName(act, PopHceService::class.java)
        ce?.let { runCatching { it.setPreferredService(act, cn) }.onFailure { e -> Log.w(TAG, "setPreferredService: $e") } }
        onDispose { ce?.let { runCatching { it.unsetPreferredService(act) } } }
    }
}

@Composable
actual fun NfcInviteReader(onInvite: (ByteArray) -> Unit, onError: (String) -> Unit) {
    val ctx = LocalContext.current
    val act = ctx.activity() ?: return
    val ok by rememberUpdatedState(onInvite)
    val err by rememberUpdatedState(onError)
    DisposableEffect(act) {
        val a = NfcAdapter.getDefaultAdapter(act)
        val main = Handler(Looper.getMainLooper())
        if (a != null) {
            val flags = NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK or
                NfcAdapter.FLAG_READER_NO_PLATFORM_SOUNDS
            runCatching {
                a.enableReaderMode(act, { tag ->
                    val iso = IsoDep.get(tag)
                    if (iso == null) {
                        main.post { err("nfc_not_isodep") }
                        return@enableReaderMode
                    }
                    try {
                        iso.connect()
                        iso.timeout = 2000
                        val b = PopApdu.parseResponse(iso.transceive(PopApdu.SELECT))
                        main.post { ok(b) }
                    } catch (e: InviteException) {
                        main.post { err(e.code) }
                    } catch (e: Exception) {
                        Log.w(TAG, "nfc read: $e")
                        main.post { err("nfc_read_failed") }
                    } finally {
                        runCatching { iso.close() }
                    }
                }, flags, null)
            }.onFailure { Log.w(TAG, "enableReaderMode: $it") }
        }
        onDispose { runCatching { a?.disableReaderMode(act) } }
    }
}

@Composable
actual fun QrCode(text: String, modifier: Modifier) {
    val bmp = remember(text) { qrBitmap(text) }
    Image(bmp.asImageBitmap(), contentDescription = "invite QR", modifier = modifier, filterQuality = FilterQuality.None)
}

/** 1 px per module, quiet zone 2; the Image scales it with nearest filtering. */
private fun qrBitmap(text: String): Bitmap {
    val hints = mapOf(EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M, EncodeHintType.MARGIN to 2)
    val m = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, 0, 0, hints)
    val w = m.width
    val h = m.height
    val px = IntArray(w * h) { i -> if (m[i % w, i / w]) 0xff000000.toInt() else 0xffffffff.toInt() }
    return Bitmap.createBitmap(px, w, h, Bitmap.Config.ARGB_8888)
}

@Composable
actual fun QrScanner(onText: (String) -> Unit, modifier: Modifier) {
    val ctx = LocalContext.current
    var granted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(ctx, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    var asked by remember { mutableStateOf(false) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it; asked = true }
    if (!ctx.packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY)) {
        Text("No camera on this device.")
        return
    }
    if (!granted) {
        DisposableEffect(Unit) {
            if (!asked) launcher.launch(Manifest.permission.CAMERA)
            onDispose {}
        }
        Box(modifier) {
            Button(onClick = { launcher.launch(Manifest.permission.CAMERA) }) {
                Text(if (asked) "Camera denied. Allow camera" else "Allow camera")
            }
        }
        return
    }
    CameraQr(onText, modifier)
}

@OptIn(ExperimentalGetImage::class)
@Composable
private fun CameraQr(onText: (String) -> Unit, modifier: Modifier) {
    val ctx = LocalContext.current
    val owner = ctx.activity() as? LifecycleOwner ?: return
    val cb by rememberUpdatedState(onText)
    val preview = remember { PreviewView(ctx).apply { scaleType = PreviewView.ScaleType.FILL_CENTER } }
    DisposableEffect(owner) {
        val exec = Executors.newSingleThreadExecutor()
        val scanner = BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
        val main = Handler(Looper.getMainLooper())
        val future = ProcessCameraProvider.getInstance(ctx)
        var provider: ProcessCameraProvider? = null
        var disposed = false
        val analysis = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
        analysis.setAnalyzer(exec) { proxy ->
            val img = proxy.image
            if (img == null) { proxy.close(); return@setAnalyzer }
            scanner.process(InputImage.fromMediaImage(img, proxy.imageInfo.rotationDegrees))
                .addOnSuccessListener { codes ->
                    codes.firstNotNullOfOrNull { it.rawValue }?.let { v -> main.post { if (!disposed) cb(v) } }
                }
                .addOnCompleteListener { proxy.close() }
        }
        future.addListener({
            if (disposed) return@addListener
            val p = runCatching { future.get() }.getOrElse { Log.w(TAG, "camera provider: $it"); return@addListener }
            provider = p
            val pv = Preview.Builder().build().also { it.surfaceProvider = preview.surfaceProvider }
            runCatching {
                p.unbindAll()
                p.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, pv, analysis)
            }.onFailure { Log.w(TAG, "camera bind: $it") }
        }, ContextCompat.getMainExecutor(ctx))
        onDispose {
            disposed = true
            runCatching { provider?.unbindAll() }
            analysis.clearAnalyzer()
            scanner.close()
            exec.shutdown()
        }
    }
    AndroidView(factory = { preview }, modifier = modifier)
}

/** §3.2 HCE. Answers SELECT(F0454E434F504F50) with the current invite ‖ 9000, else 6A82. */
class PopHceService : android.nfc.cardemulation.HostApduService() {
    override fun processCommandApdu(commandApdu: ByteArray?, extras: android.os.Bundle?): ByteArray {
        val apdu = commandApdu ?: return PopApdu.SW_NOT_FOUND
        val r = PopApdu.respond(apdu, InviteBeacon.current())
        Log.i(TAG, "hce ${apdu.toHex().take(40)} -> ${r.size} bytes")
        return r
    }

    override fun onDeactivated(reason: Int) {}
}
