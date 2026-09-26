package com.enconomy.pop

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import kotlinx.coroutines.await
import kotlinx.coroutines.launch

actual object Prefs {
    actual fun get(key: String): String? = jsStorageGet("pop.$key")
    actual fun set(key: String, value: String?) {
        if (value == null) jsStorageRemove("pop.$key") else jsStorageSet("pop.$key", value)
    }
}

/** "web/<browser> <os>" from the user agent (the full UA goes into the run meta). */
actual fun deviceModel(): String {
    val ua = jsUserAgent()
    val os = when {
        "Android" in ua -> "Android"
        "iPhone" in ua || "iPad" in ua -> "iOS"
        "Mac OS X" in ua -> "Mac"
        "Windows" in ua -> "Windows"
        "Linux" in ua -> "Linux"
        else -> "?"
    }
    val br = when {
        "Edg/" in ua -> "Edge"
        "Firefox/" in ua -> "Firefox"
        "Chrome/" in ua || "CriOS/" in ua -> "Chrome"
        "Safari/" in ua -> "Safari"
        else -> "browser"
    }
    return "web/$br $os"
}

actual fun unixMs(): Long = jsDateNow().toLong()

/** performance.now() in ns: the clock the audio glue maps context time onto. */
actual fun monoNanos(): Long = (jsPerfNow() * 1e6).toLong()

actual fun isDebugBuild(): Boolean {
    val h = jsHostname()
    return h == "localhost" || h == "127.0.0.1" || Regex("[?&]debug(=|&|$)").containsMatchIn(jsSearch())
}

actual fun openExternalUrl(url: String): Boolean = jsOpen(url)

@Composable
actual fun KeepScreenOn(on: Boolean) {
    DisposableEffect(on) {
        jsWakeLock(on)
        onDispose { if (on) jsWakeLock(false) }
    }
}

/** Cached by the glue: true once getUserMedia gave a stream in this tab. */
actual fun hasMicPermission(): Boolean = audioMicGranted()

/** The launcher runs inside the click handler, so unlock() (AudioContext + getUserMedia) keeps its user gesture. */
@Composable
actual fun rememberMicPermissionRequest(onResult: (Boolean) -> Unit): () -> Unit {
    val cb = rememberUpdatedState(onResult)
    val scope = rememberCoroutineScope()
    return {
        if (audioMicGranted() && audioUnlocked()) cb.value(true)
        else {
            val p = audioUnlock() // started synchronously in the gesture
            scope.launch {
                val ok = runCatching { p.await<JsAny?>() }.isSuccess && audioMicGranted()
                cb.value(ok)
            }
        }
    }
}
