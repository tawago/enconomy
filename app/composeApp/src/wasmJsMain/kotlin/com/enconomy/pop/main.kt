package com.enconomy.pop

import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.window.ComposeViewport
import kotlinx.browser.document
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Tab-lifetime controller, like PopApplication.controller on Android. */
private val controller by lazy { PopController(createDeviceKeystore()) }

private fun onVisible(f: () -> Unit): Unit =
    js("document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') f(); })")

@OptIn(ExperimentalComposeUiApi::class)
fun main() {
    ComposeViewport(document.body!!) { App(controller) }
    onVisible { controller.onForeground() }
    val forConsumer = sessionForConsumer()
    if (forConsumer && controller.state.value.enrollment != null) controller.host()
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

/**
 * /app/?chain_id=..&consumer=..&ctx_hash=..&deliver=..: host with this context, and hand the signed record to `deliver`
 * after a NEAR. The core checks the context, the consumer checks the record. The URL stays, so Host keeps it in this tab.
 * The record holds device keys and transcripts, so `deliver` must be on the origin baked in at build time. Any other link
 * is treated as no link at all.
 */
private fun sessionForConsumer(): Boolean {
    val chainId = jsQuery("chain_id")?.toLongOrNull() ?: return false
    val consumer = jsQuery("consumer") ?: return false
    val ctxHash = jsQuery("ctx_hash") ?: return false
    val deliver = jsQuery("deliver") ?: return false
    if (jsOriginOf(deliver) != PopBuildConfig.DELIVER_ORIGIN) {
        println("deliver refused: not on the origin this build allows")
        return false
    }
    controller.hostContext = buildJsonObject {
        put("chain_id", chainId)
        put("consumer", consumer)
        put("ctx_hash", ctxHash)
    }
    controller.onPresence = { record -> jsDeliver(deliver, record) }
    return true
}

private fun jsQuery(name: String): String? = js("new URLSearchParams(location.search).get(name)")

private fun jsOriginOf(url: String): String? = js("(function(){ try { return new URL(url).origin; } catch (e) { return null; } })()")

/** Tries again only when no answer came back. A refusal is final, and the consumer's page shows the outcome. */
private fun jsDeliver(url: String, body: String): Unit = js("""(async function(){
  for (let i = 0; i < 5; i++) {
    try { const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: body }); console.log('presence record delivered', r.status); return; }
    catch (e) { console.log('presence record not delivered', String(e)); await new Promise(function(k){ setTimeout(k, 2000); }); }
  }
})()""")

private fun decodeUriComponent(s: String): String = js("(function(){ try { return decodeURIComponent(s); } catch (e) { return s; } })()")
