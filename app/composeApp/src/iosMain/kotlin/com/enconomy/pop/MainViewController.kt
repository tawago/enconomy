package com.enconomy.pop

import androidx.compose.ui.window.ComposeUIViewController
import platform.UIKit.UIViewController

/** Process-lifetime controller, like PopApplication.controller on Android. */
private val controller by lazy { PopController(createDeviceKeystore()) }

fun MainViewController(): UIViewController = ComposeUIViewController { App(controller) }.also {
    // ios-deploy --envs "POP_BENCH=180ca04b_48k_A POP_FORCE=1": run the prover bench at launch
    platform.Foundation.NSProcessInfo.processInfo.environment["POP_BENCH"]?.let { n ->
        controller.openBench(); controller.benchRun(n.toString(), platform.Foundation.NSProcessInfo.processInfo.environment["POP_FORCE"] != null)
    }
}

/** SwiftUI .onOpenURL / scene active: enconomy://worldid back from World App (docs/worldid/01 §12). */
fun onOpenUrl(url: String?) {
    if (url == null || WorldId.isReturnLink(url)) controller.onWorldIdReturn()
}
