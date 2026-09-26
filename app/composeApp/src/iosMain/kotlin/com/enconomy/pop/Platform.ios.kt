@file:OptIn(ExperimentalForeignApi::class)

package com.enconomy.pop

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.rememberUpdatedState
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.alloc
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.toKString
import platform.AVFAudio.AVAudioSession
import platform.AVFAudio.AVAudioSessionRecordPermissionGranted
import platform.Foundation.NSDate
import platform.Foundation.NSProcessInfo
import platform.Foundation.NSUserDefaults
import platform.Foundation.timeIntervalSince1970
import platform.UIKit.UIApplication
import platform.darwin.dispatch_async
import platform.darwin.dispatch_get_main_queue
import platform.posix.CLOCK_UPTIME_RAW
import platform.posix.clock_gettime_nsec_np
import platform.posix.uname
import platform.posix.utsname

actual object Prefs {
    private val d get() = NSUserDefaults.standardUserDefaults
    actual fun get(key: String): String? = d.stringForKey("pop.$key")
    actual fun set(key: String, value: String?) {
        if (value == null) d.removeObjectForKey("pop.$key") else d.setObject(value, "pop.$key")
    }
}

/** utsname.machine, e.g. iPhone17,1 (simulator: the simulated model). */
actual fun deviceModel(): String {
    NSProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"]?.let { return it as String }
    return memScoped {
        val u = alloc<utsname>()
        if (uname(u.ptr) != 0) "unknown" else u.machine.toKString()
    }
}

actual fun unixMs(): Long = (NSDate().timeIntervalSince1970 * 1000.0).toLong()

/** mach_absolute_time in ns (CLOCK_UPTIME_RAW): same clock as AVAudioTime.hostTime. */
actual fun monoNanos(): Long = clock_gettime_nsec_np(CLOCK_UPTIME_RAW.toUInt()).toLong()

@Composable
actual fun KeepScreenOn(on: Boolean) {
    DisposableEffect(on) {
        UIApplication.sharedApplication.idleTimerDisabled = on
        onDispose { UIApplication.sharedApplication.idleTimerDisabled = false }
    }
}

actual fun hasMicPermission(): Boolean =
    AVAudioSession.sharedInstance().recordPermission == AVAudioSessionRecordPermissionGranted

@Composable
actual fun rememberMicPermissionRequest(onResult: (Boolean) -> Unit): () -> Unit {
    val cb = rememberUpdatedState(onResult)
    return {
        if (hasMicPermission()) cb.value(true) else AVAudioSession.sharedInstance().requestRecordPermission { ok ->
            dispatch_async(dispatch_get_main_queue()) { cb.value(ok) }
        }
    }
}

@OptIn(kotlin.experimental.ExperimentalNativeApi::class)
actual fun isDebugBuild(): Boolean = kotlin.native.Platform.isDebugBinary

actual fun openExternalUrl(url: String): Boolean {
    val u = platform.Foundation.NSURL.URLWithString(url) ?: return false
    UIApplication.sharedApplication.openURL(u, options = emptyMap<Any?, Any>(), completionHandler = null)
    return true
}
