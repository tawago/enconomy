package com.enconomy.pop

import android.content.Context
import android.os.Build

actual object Prefs {
    private val sp get() = PopApplication.instance.getSharedPreferences("pop", Context.MODE_PRIVATE)
    actual fun get(key: String): String? = sp.getString(key, null)
    actual fun set(key: String, value: String?) {
        sp.edit().apply { if (value == null) remove(key) else putString(key, value) }.apply()
    }
}

actual fun createDeviceKeystore(): DeviceKeystore = AndroidDeviceKeystore(PopApplication.instance)

actual fun deviceModel(): String = Build.MODEL ?: "unknown"

actual fun unixMs(): Long = System.currentTimeMillis()

actual fun isDebugBuild(): Boolean = runCatching {
    (PopApplication.instance.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
}.getOrDefault(false)

actual fun openExternalUrl(url: String): Boolean = try {
    val i = android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))
        .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
    PopApplication.instance.startActivity(i)
    true
} catch (_: android.content.ActivityNotFoundException) {
    false
}

actual fun platformDefaultBaseUrl(baked: String): String = baked
