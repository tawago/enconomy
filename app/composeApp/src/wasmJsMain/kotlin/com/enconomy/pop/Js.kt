package com.enconomy.pop

import kotlin.js.Promise

/**
 * Small JS bridge for the web build. Bytes cross as hex strings, structured results as JSON strings, and
 * big sample buffers stay JS objects (read / written per index), so no typed-array bindings are needed.
 */

// ---- page ----

internal fun jsPerfNow(): Double = js("performance.now()")
internal fun jsDateNow(): Double = js("Date.now()")
internal fun jsUserAgent(): String = js("navigator.userAgent || ''")
internal fun jsHostname(): String = js("location.hostname || ''")
internal fun jsSearch(): String = js("location.search || ''")
internal fun jsHash(): String = js("location.hash || ''")
internal fun jsClearHash(): Unit = js("history.replaceState(null, '', location.pathname + location.search)")
internal fun jsOpen(url: String): Boolean = js("!!window.open(url, '_blank')")
internal fun jsLog(msg: String): Unit = js("console.log(msg)")

internal fun jsStorageGet(key: String): String? = js("(function(){ try { return localStorage.getItem(key); } catch (e) { return null; } })()")
internal fun jsStorageSet(key: String, value: String): Unit = js("(function(){ try { localStorage.setItem(key, value); } catch (e) {} })()")
internal fun jsStorageRemove(key: String): Unit = js("(function(){ try { localStorage.removeItem(key); } catch (e) {} })()")

internal fun jsRandomHex(n: Int): String =
    js("(function(){ const b = new Uint8Array(n); crypto.getRandomValues(b); return Array.from(b, x => x.toString(16).padStart(2, '0')).join(''); })()")

internal fun jsDeviceMemoryGb(): Double = js("(navigator.deviceMemory || 0)")
internal fun jsSaveData(): Int = js("(navigator.connection ? (navigator.connection.saveData ? 1 : 0) : -1)")

/** Wake Lock on/off (glue in index.html: re-requested on visibilitychange while wanted). */
internal fun jsWakeLock(on: Boolean): Unit = js("window.popWake && window.popWake.set(on)")

// ---- audio glue (pop-audio.js, window.popAudio) ----

internal fun audioUnlocked(): Boolean = js("!!(window.popAudio && window.popAudio.unlocked())")
internal fun audioMicGranted(): Boolean = js("!!(window.popAudio && window.popAudio.micGranted())")
internal fun audioUnlock(): Promise<JsAny?> = js("window.popAudio.unlock()")
/** JSON: sampleRate, baseLatency, outputLatency, inputLatency, settings{...}, state, drops, unlocked. */
internal fun audioInfoJson(): String = js("window.popAudio ? window.popAudio.info() : '{}'")
internal fun audioNewBuffer(n: Int): JsAny = js("new Float32Array(n)")
internal fun audioBufSet(buf: JsAny, i: Int, v: Float): Unit = js("buf[i] = v")
internal fun audioBufGet(buf: JsAny, i: Int): Float = js("buf[i]")
internal fun audioBufLen(buf: JsAny): Int = js("buf.length")
internal fun audioPerfToCtx(perfMs: Double): Double = js("window.popAudio.perfToCtx(perfMs)")
internal fun audioCtxToPerf(ctxS: Double): Double = js("window.popAudio.ctxToPerf(ctxS)")
internal fun audioCtxNow(): Double = js("window.popAudio.ctxNow()")
/** Schedules [buf] to start at context time [whenS]; returns the context time actually used. */
internal fun audioSchedule(buf: JsAny, whenS: Double): Double = js("window.popAudio.schedule(buf, whenS)")
/** Resolves with a Float32Array of [n] mic frames starting at context frame [start]. */
internal fun audioCollect(start: Double, n: Int, timeoutMs: Int): Promise<JsAny?> = js("window.popAudio.collect(start, n, timeoutMs)")
internal fun audioStopAll(): Unit = js("window.popAudio && window.popAudio.stopAll()")

// ---- QR glue (pop-qr.js, window.popQr) ----

/** Opens the fullscreen camera overlay; resolves with the decoded text, or null when closed. */
internal fun qrScan(): Promise<JsAny?> = js("window.popQr.scan()")
internal fun qrClose(): Unit = js("window.popQr && window.popQr.close()")
internal fun qrSetDecoder(f: JsAny): Unit = js("window.popQr && window.popQr.setDecoder(f)")

internal fun jsStr(v: JsAny?): String? = v?.let { jsToStr(it) }
private fun jsToStr(v: JsAny): String? = js("(typeof v === 'string') ? v : null")
