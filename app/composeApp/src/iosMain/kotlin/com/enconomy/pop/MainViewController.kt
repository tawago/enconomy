package com.enconomy.pop

import androidx.compose.ui.window.ComposeUIViewController
import platform.UIKit.UIViewController

/** Process-lifetime controller, like PopApplication.controller on Android. */
private val controller by lazy { PopController(createDeviceKeystore()) }

fun MainViewController(): UIViewController = ComposeUIViewController { App(controller) }
