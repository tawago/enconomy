package com.enconomy.pop

import androidx.compose.ui.window.ComposeUIViewController
import platform.UIKit.UIViewController

/** Process-lifetime controller, like PopApplication.controller on Android. */
private val controller by lazy { PopController(createDeviceKeystore()) }

fun MainViewController(): UIViewController = ComposeUIViewController { App(controller) }

/** SwiftUI .onOpenURL / scene active: enconomy://worldid back from World App (docs/worldid/01 §12). */
fun onOpenUrl(url: String?) {
    if (url == null || WorldId.isReturnLink(url)) controller.onWorldIdReturn()
}
