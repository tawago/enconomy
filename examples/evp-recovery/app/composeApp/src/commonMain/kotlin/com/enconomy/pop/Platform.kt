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

/** Default server URL: the baked one; the web build served by the PoP server uses the page origin. */
expect fun platformDefaultBaseUrl(baked: String): String
