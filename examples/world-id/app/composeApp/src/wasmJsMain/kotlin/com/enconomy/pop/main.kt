package com.enconomy.pop

import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.window.ComposeViewport
import kotlinx.browser.document
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** Tab-lifetime controller, like PopApplication.controller on Android. */
private val controller by lazy { PopController(createDeviceKeystore()) }

private fun onVisible(f: () -> Unit): Unit =
    js("document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') f(); })")

@OptIn(ExperimentalComposeUiApi::class)
fun main() {
    ComposeViewport(document.body!!) { App(controller) }
    onVisible { controller.onForeground() }
    // ens.enconomy.dev/app/#pop1:...: a phone camera app opened an invite link
    val h = jsHash().removePrefix("#")
    if (h.startsWith(Invite.QR_PREFIX, ignoreCase = true)) {
        jsClearHash()
        val text = decodeUriComponent(h)
        if (controller.state.value.enrollment == null) return // enroll first; the invite expires anyway
        MainScope().launch {
            controller.join()
            withTimeoutOrNull(15_000) { controller.state.first { it.screen == Screen.Join && !it.busy } } ?: return@launch
            controller.onQrText(text)
        }
    }
}

private fun decodeUriComponent(s: String): String = js("(function(){ try { return decodeURIComponent(s); } catch (e) { return s; } })()")
