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
