@file:OptIn(kotlin.experimental.ExperimentalNativeApi::class)

package com.enconomy.pop

import androidx.compose.ui.window.ComposeUIViewController
import platform.Foundation.NSLog
import platform.UIKit.UIViewController

/** Process-lifetime controller, like PopApplication.controller on Android. */
private val controller by lazy { PopController(createDeviceKeystore()) }

private var hookSet = false

/**
 * Kotlin/Native ends the process on an uncaught exception; the hook only gets it into the device log
 * (Console.app / idevicesyslog, tag "pop:") before that. Coroutines are caught earlier, in the controller.
 */
private fun installCrashLog() {
    if (hookSet) return
    hookSet = true
    setUnhandledExceptionHook { e ->
        val msg = "pop: uncaught ${e::class.simpleName}: ${e.message}\n${e.stackTraceToString()}"
        println(msg)
        NSLog(msg.replace("%", "%%"))
    }
}

fun MainViewController(): UIViewController {
    installCrashLog()
    return ComposeUIViewController { App(controller) }
}

/**
 * SwiftUI .onOpenURL (enconomy://worldid back from World App, docs/worldid/01 §12) and scene active (url = null):
 * the app is in front again, so resync the server clock and restart the World ID poll.
 */
fun onOpenUrl(url: String?) {
    if (url == null) controller.onForeground()
    else if (WorldId.isReturnLink(url)) controller.onWorldIdReturn()
}
