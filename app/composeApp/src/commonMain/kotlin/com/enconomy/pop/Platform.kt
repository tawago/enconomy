package com.enconomy.pop

/** Small persisted key/value store (server URL, enrollment). */
expect object Prefs {
    fun get(key: String): String?
    fun set(key: String, value: String?)
}

expect fun createDeviceKeystore(): DeviceKeystore

/** Build.MODEL */
expect fun deviceModel(): String

expect fun unixMs(): Long

/** Debuggable build (Android FLAG_DEBUGGABLE, iOS debug binary). Gates the `test` context kind (docs/worldid/01 §12). */
expect fun isDebugBuild(): Boolean

/** Open [url] in another app (World ID connector link, docs/worldid/01 §6.7). false = nothing could open it. */
expect fun openExternalUrl(url: String): Boolean

/** Default server URL: the baked one; the web build served by the PoP server uses the page origin. */
expect fun platformDefaultBaseUrl(baked: String): String
