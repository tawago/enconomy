package com.enconomy.pop

import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.window.ComposeViewport
import kotlinx.browser.document
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

/** Tab-lifetime controller, like PopApplication.controller on Android. */
private val controller by lazy {
    PopController(createDeviceKeystore(), onSessionCreated = { inv ->
        // sid: the nonce formula's bytes16, which is session_id (server/pop/sessions.py), lowercase hex
        jsStorageSet("evp_session", buildJsonObject {
            put("session_id", inv.session_id)
            put("not_before", inv.not_before)
            put("sid", inv.session_id)
        }.toString())
    })
}

private fun onVisible(f: () -> Unit): Unit =
    js("document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') f(); })")

@OptIn(ExperimentalComposeUiApi::class)
fun main() {
    jsQueryParam("core")?.let { Prefs.set("baseUrl", it) } // before the controller reads it
    ComposeViewport(document.body!!) { App(controller) }
    onVisible { controller.onForeground() }
    // ?context=<base64url JSON>: host with it as soon as this device is enrolled
    jsQueryParam("context")?.let { c ->
        val context = popJson.parseToJsonElement(c.fromB64Url().decodeToString()).jsonObject
        MainScope().launch {
            controller.state.first { it.enrollment != null && it.screen == Screen.Home && !it.busy }
            controller.host(context)
        }
    }
    // /app/#pop1:...: a phone camera app opened an invite link
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
